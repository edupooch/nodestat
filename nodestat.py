#!/usr/bin/env python3
import subprocess
import argparse
import math
import re 
import os


def parse_tres(tres_str):
    tres = {}
    #cpu, mem, gres/gpu
    for item in tres_str.split(","):
        key, val = item.split("=")
        tres[key] = val.strip()
    if 'cpu' not in tres:
        tres['cpu'] = '0'
    if 'mem' not in tres:
        tres['mem'] = '0G'
    if 'gres/gpu' not in tres:
        tres['gres/gpu'] = '0'
    return tres

def parse_gres(gres_str):
    """Parse Gres= or GresUsed= string into {gpu_type: count} dict."""
    result = {}
    if not gres_str or gres_str in ('(null)', 'N/A'):
        return result
    # Untyped GRES shows up in GresUsed= as gpu:(null):N; drop the (null) type
    # so it matches Gres=gpu:N
    gres_str = gres_str.replace(':(null):', ':')
    # Strip all parenthetical suffixes (e.g. (IDX:0,1,2)) BEFORE splitting by comma
    # so that commas inside parens don't corrupt the split
    gres_str = re.sub(r'\([^)]*\)', '', gres_str)
    for item in gres_str.split(','):
        item = item.strip()
        if not item:
            continue
        parts = item.split(':')
        if not parts or parts[0] != 'gpu':
            continue
        if len(parts) == 3:
            gpu_type, count_str = parts[1], parts[2]
        elif len(parts) == 2:
            gpu_type, count_str = 'gpu', parts[1]
        else:
            continue
        try:
            result[gpu_type] = result.get(gpu_type, 0) + int(count_str)
        except ValueError:
            pass
    return result

def expand_hostlist(hostlist):
    """Expand a Slurm hostlist such as 'gpu[01-03,07],gaia' into node names."""
    if hostlist in ('', '(null)'):
        return []
    nodes = []
    # split on commas outside brackets
    for item in re.findall(r'(?:[^,\[]|\[[^\]]*\])+', hostlist):
        if '[' not in item:
            nodes.append(item)
            continue
        prefix, rest = item.split('[', 1)
        ranges, suffix = rest.split(']', 1)
        for r in ranges.split(','):
            start, _, end = r.partition('-')
            for i in range(int(start), int(end or start) + 1):
                # keep zero padding: gpu[01-03] -> gpu01
                nodes.append(f"{prefix}{i:0{len(start)}d}{suffix}")
    return nodes

def count_ids(ids):
    """Count the CPUs in a CPU_IDs list such as '24-31,40-41'."""
    total = 0
    for r in ids.split(','):
        start, _, end = r.partition('-')
        total += int(end or start) - int(start) + 1
    return total

def get_slurm_node_info():
    node_info = {}
    node_name = None
    # -d: GresUsed= is only printed in the detailed output
    command = "scontrol -d show node"
    result = subprocess.run(command.split(), stdout=subprocess.PIPE, universal_newlines=True)

    for line in result.stdout.split('\n'):
        line = line.strip()
        if line.startswith('NodeName'):
            node_name = line.split('=')[1].split(' ')[0]
            node_info[node_name] = {}
        elif line.startswith('Partitions'):
            partition_name = line.split('=')[1]
            node_info[node_name]['partition'] = partition_name
        #CfgTRES
        elif line.startswith('CfgTRES'):
            line = line.replace('CfgTRES=', '')
            cfg_tres = parse_tres(line)
            node_info[node_name]['cfg_tres'] = cfg_tres
        #AllocTRES
        elif line.startswith('AllocTRES'):
            line = line.replace('AllocTRES=', '')
            if line == '':
                alloc_tres = {'cpu': '0', 'mem': '0G', 'gres/gpu': '0'}
            else:
                alloc_tres = parse_tres(line)
            node_info[node_name]['alloc_tres'] = alloc_tres
        #status
        elif line.startswith('State'):
            state = line.split('=')[1].split(' ')[0].strip()
            node_info[node_name]['state'] = state
        # Gres/GresUsed: use regex since they may share a line with other fields
        if node_name and 'Gres=' in line and 'CfgTRES' not in line and 'AllocTRES' not in line:
            m = re.search(r'\bGres=(\S+)', line)
            if m:
                node_info[node_name]['gres'] = parse_gres(m.group(1))
        if node_name and 'GresUsed=' in line:
            m = re.search(r'GresUsed=(\S+)', line)
            if m:
                node_info[node_name]['gres_used'] = parse_gres(m.group(1))
    
    # Exclude nodes not assigned to any partition
    node_info = {k: v for k, v in node_info.items() if 'partition' in v}
    # Ensure gres/gres_used always present
    for v in node_info.values():
        v.setdefault('gres', {})
        v.setdefault('gres_used', {})
    return node_info

def parse_mem(mem_str):
    # Slurm's units are binary: 1G = 1024M
    if mem_str.endswith("M"):
        mem = float(mem_str[:-1]) / 1024
    elif mem_str.endswith("K"):
        mem = float(mem_str[:-1]) / 1024 / 1024
    elif mem_str.endswith("T"):
        mem = float(mem_str[:-1]) * 1024
    elif mem_str.endswith("G"):
        mem = float(mem_str[:-1])
    else:
        mem = float(mem_str) / 1024  # no unit: MB
    return mem

def format_mem(mem):
    """GB with one decimal below 10G, so small jobs don't round to 0."""
    return f"{mem:.1f}" if mem < 10 else f"{mem:.0f}"

def job_tres_on_node(job, node_name):
    """TRES a job holds on one node (AllocTRES is the whole job's total)."""
    return job['per_node'].get(node_name, job['tres'])

def get_slurm_jobs():
    # -d: prints the per-node allocation (Nodes= CPU_IDs= Mem= GRES=)
    result = subprocess.run(["scontrol", "-d", "show", "job"], stdout=subprocess.PIPE, universal_newlines=True)
    job_str = result.stdout.split('\n\n')
    job_info = {}
    for job in job_str:
        job = job.strip()
        if len(job.split('JobId=')) == 1:
            continue
        job_id = job.split('JobId=')[1].split(' ')[0]
        job_info[job_id] = {}
        node_list_match = re.search(r'\sNodeList=(\S+)', job)
        job_info[job_id]['nodes'] = expand_hostlist(node_list_match.group(1)) if node_list_match else []
        job_info[job_id]['state'] = job.split('JobState=')[1].split(' ')[0]
        job_info[job_id]['user'] = job.split('UserId=')[1].split(' ')[0].split('(')[0]
        #TRES 
        # Older Slurm versions print TRES= instead of AllocTRES=
        # (\b so that ReqTRES= does not match)
        tres_match = re.search(r'AllocTRES=(\S+)', job) or re.search(r'\bTRES=(\S+)', job)
        tres_str = tres_match.group(1) if tres_match else '(null)'
        if 'null' in tres_str:
            tres_str = 'cpu=0,mem=0G,gres/gpu=0'
        tres = parse_tres(tres_str)
        job_info[job_id]['tres'] = tres
        # Multi-node jobs: AllocTRES is the total over all nodes, so keep
        # what each node holds
        per_node = {}
        if len(job_info[job_id]['nodes']) > 1:
            for nodes, cpu_ids, mem, gres in re.findall(r'^\s*Nodes=(\S+) CPU_IDs=(\S+) Mem=(\d+) GRES=(\S*)', job, re.M):
                gpus = parse_gres(gres)
                node_tres = {'cpu': str(count_ids(cpu_ids)), 'mem': f"{mem}M", 'gres/gpu': str(sum(gpus.values()))}
                node_tres.update({f"gres/gpu:{t}": str(n) for t, n in gpus.items() if t != 'gpu'})
                for node in expand_hostlist(nodes):
                    per_node[node] = node_tres
        job_info[job_id]['per_node'] = per_node

    return job_info

def get_node_default_values():
    default = {}
    try:
        with open(os.environ.get("SLURM_CONF", "/etc/slurm/slurm.conf"), "r") as f:
            lines = f.readlines()
    except OSError:
        return default
    for line in lines:
        if "Nodes=" in line:
            node_names = line.split("Nodes=")[1].split(" ")[0].split(",")
            mem, cpu = 0, 0
            if "DefMemPerCPU=" in line: 
                mem = int(line.split("DefMemPerCPU=")[1].split(" ")[0])
            if "DefCpuPerGPU=" in line:
                cpu = int(line.split("DefCpuPerGPU=")[1].split(" ")[0])

            for node_name in node_names:
                default[node_name] = {"DefMemPerCPU": mem, "DefCpuPerGPU": cpu}
    return default

def get_nodes_in_reservation(reservation):
    command = f"scontrol show res {reservation}"
    result = subprocess.run(command.split(), stdout=subprocess.PIPE, universal_newlines=True)
    nodes_line = [line for line in result.stdout.split('\n') if line.strip().startswith('Nodes=')]

    if nodes_line:
        return expand_hostlist(nodes_line[0].split('=')[1].split()[0])

    return []
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--jobs", help="show active jobs on the nodes", action="store_true")
    parser.add_argument("-m", "--me", help="show only my jobs", action="store_true")
    parser.add_argument("-q", "--queue", help="show jobs in the queue", action="store_true")
    parser.add_argument("-t", "--total", help="show total resources", action="store_true")
    parser.add_argument("-r", "--reservation", help="show resources inside reservation")
    parser.add_argument("-g", "--gpu", help="show only GPU nodes with detailed per-type GPU breakdown", action="store_true")

    args = parser.parse_args()
    show_jobs = args.jobs
    show_my_jobs = args.me
    show_queue = args.queue
    show_total = args.total
    reservation_name = args.reservation
    show_gpu_detail = args.gpu

    node_info = get_slurm_node_info()
    if show_jobs or show_my_jobs:
        job_info = get_slurm_jobs()
        default_values = get_node_default_values()
    elif show_gpu_detail:
        job_info = get_slurm_jobs()

    if reservation_name:
        reservation_nodes = get_nodes_in_reservation(reservation_name)
        node_info = {node: info for node, info in node_info.items() if node in reservation_nodes}

    if show_gpu_detail:
        node_info = {k: v for k, v in node_info.items() if int(v.get('cfg_tres', {}).get('gres/gpu', '0')) > 0}

    if show_gpu_detail and (show_jobs or show_my_jobs):
        suffix = " | JOBS + GPU"
    elif show_gpu_detail:
        suffix = " | GPU DETAIL"
    elif show_jobs or show_my_jobs:
        suffix = " | JOBS"
    else:
        suffix = " "
    print("{:<15}{:<15}{:<12}{:<10}{:<8}{:<10}".format("PARTITION", "NODE", "CPUS", "GPUS", "MEM (G)", suffix))

    partitions = set([info['partition'] for node_name, info in node_info.items()])
    partitions = sorted(partitions)
    if "cpu" in partitions:
        partitions.remove("cpu")
        partitions.append("cpu")

    global_total_cpu = 0
    global_total_gpu = 0
    global_total_mem = 0
    global_available_cpu = 0
    global_available_gpu = 0
    global_available_mem = 0
    global_total_nodes = 0

    for partition in partitions:
        info_partition = [x for x in node_info.items() if x[1]['partition'] == partition]
        for node_name, info in info_partition:
            global_total_nodes += 1
            available_cpu = int(info['cfg_tres']['cpu']) - int(info['alloc_tres']['cpu'])
            int_total_cpu = int(info['cfg_tres']['cpu'])    
            global_available_cpu += available_cpu
            global_total_cpu += int_total_cpu

            total_cpu = "\033[90m" + "/" + str(int_total_cpu) + "\033[0m"
            if available_cpu == 0:
                available_cpu = "\033[91m" + str(available_cpu) + "\033[0m"
            elif available_cpu <= 0.5 * int_total_cpu:
                available_cpu = "\033[33m" + str(available_cpu) + "\033[0m"
            else:
                available_cpu = "\033[32m" + str(available_cpu) + "\033[0m"
            available_cpu = f"{available_cpu}{total_cpu}"

            available_gpu = int(info['cfg_tres']['gres/gpu']) - int(info['alloc_tres']['gres/gpu'])
            int_total_gpu = int(info['cfg_tres']['gres/gpu'])
            global_available_gpu += available_gpu
            global_total_gpu += int_total_gpu
            
            total_gpu = "\033[90m" + "/" + str(int_total_gpu) + "\033[0m"

            if available_gpu == 0:
                available_gpu = "\033[91m" + str(available_gpu) + "\033[0m"
            elif available_gpu <= 0.5 * int_total_gpu:
                available_gpu = "\033[33m" + str(available_gpu) + "\033[0m"
            else:
                available_gpu = "\033[32m" + str(available_gpu) + "\033[0m"
            
            # on cpu servers replace 0/0 with -
            if int(info['cfg_tres']['gres/gpu']) == 0:
                available_gpu =  "\033[91m" + " " + "\033[0m"
                total_gpu = "\033[90m" + "-" + " " + "\033[0m"        

            available_gpu = f"{available_gpu}{total_gpu}"

            available_mem = int(parse_mem(info['cfg_tres']['mem']) - parse_mem(info['alloc_tres']['mem']))
            total_mem = int(parse_mem(info['cfg_tres']['mem']))
            global_available_mem += available_mem
            global_total_mem += total_mem

            total_mem = "\033[90m" + "/" + str(total_mem) + "\033[0m"
            if available_mem == 0:
                available_mem = "\033[91m" + str(available_mem) + "\033[0m"
            else:
                available_mem = "\033[32m" + str(available_mem) + "\033[0m"
    
            available_mem = f"{available_mem}{total_mem}"
            state = info['state']
            # State=<base>[+<flag>...], e.g. MIXED+DRAIN, DOWN+NOT_RESPONDING
            base_state, *state_flags = state.split('+')
            blocking_flags = [f for f in state_flags if f in ('DRAIN', 'RESERVED', 'MAINTENANCE', 'FAIL', 'POWERED_DOWN')]

            if base_state not in ('IDLE', 'MIXED', 'ALLOCATED') or blocking_flags:
                if not reservation_name:
                    if "RESERVED" in state:
                        available_cpu = "\033[90m"  + "RESERVED" + "\033[0m" + "\033[32m" + "" + "\033[0m"
                    else:
                        label = blocking_flags[0] if blocking_flags else base_state
                        available_cpu = "\033[90m"  + label + "\033[0m" + "\033[32m" + "" + "\033[0m"
                    
                    available_gpu = "\033[91m"  + " " + "\033[0m" + "\033[32m" + "" + "\033[0m"
                    available_mem = "\033[91m"  + " " + "\033[0m" + "\033[32m" + "" + "\033[0m"
    
            out = "{:<15}{:<15}{:<30}{:<28}{:<26}{}".format(info['partition'], node_name, available_cpu, available_gpu, available_mem, " | " if show_jobs or show_my_jobs or show_gpu_detail else " ")
            if show_jobs or show_my_jobs:
                if show_jobs:
                    result = subprocess.run(["squeue", "-o", "%.12u,%A", "--nodelist=" + node_name], stdout=subprocess.PIPE, universal_newlines=True)
                if show_my_jobs:
                    result = subprocess.run(["squeue", "-o", "%.12j,%A", "--me", "--nodelist=" + node_name], stdout=subprocess.PIPE, universal_newlines=True)

                text = result.stdout
                text = text.split('\n')

                if len(text) > 1:
                    for line in text[1:-1]:
                        line = line.strip()
                        if line != "":
                            # job names may contain commas: split from the right
                            # %A: the job's own JobId, also for array
                            # elements and het-job components
                            user, jobid = line.rsplit(',', 1)
                            job = job_info.get(jobid)
                            if job is None or job['state'] == 'PENDING':
                                # ended or started between scontrol and squeue
                                # (an array's last task takes over the base
                                # JobId of the pending record)
                                continue
                            tres = job_tres_on_node(job, node_name)
                            cpu = tres['cpu']
                            gpu = tres['gres/gpu']
                            mem = parse_mem(tres['mem'])

                            total_gpu = info['cfg_tres']['gres/gpu']
                            node_defaults = default_values.get(node_name)
                            if node_defaults:
                                recommended_cpu = node_defaults['DefCpuPerGPU'] * int(gpu) if int(gpu) > 0 else 2                
                                recommended_mem = parse_mem(str(node_defaults['DefMemPerCPU'] * int(cpu)) + "M")
                                if int(cpu) <= recommended_cpu:
                                    cpu = "\033[33m" + cpu + "\033[0m"
                                else: 
                                    cpu = "\033[91m" + cpu + "\033[0m"
                                if mem <= recommended_mem:
                                    mem = "\033[33m" + format_mem(mem) + "G" + "\033[0m"
                                else:
                                    mem = "\033[91m" + format_mem(mem) + "G" + "\033[0m"
                            else:
                                mem = "\033[33m" + format_mem(mem) + "G" + "\033[0m"

                            if gpu == "0": #gray
                                gpu = "\033[90m" + gpu + "\033[0m"
                            else:
                                gpu = "\033[33m" + gpu + "\033[0m"

                            #bold user 
                            user = "\033[1m" + user + "\033[0m"
                        
                            res = f"{cpu}:{gpu}:{mem}"

                            out += f"{user}({res}), "
                    out = out[:-2] if out.endswith(", ") else out

            if show_gpu_detail:
                gres_cfg = info.get('gres', {})
                # Aggregate per-MIG-type usage from AllocTRES of running jobs
                # (more reliable than GresUsed= which may not break down by MIG type)
                mig_used = {}
                for jdata in job_info.values():
                    if jdata.get('state') != 'RUNNING':
                        continue
                    if node_name not in jdata.get('nodes', []):
                        continue
                    for key, val in job_tres_on_node(jdata, node_name).items():
                        if key.startswith('gres/gpu:'):
                            gpu_type = key.split(':', 1)[1]
                            try:
                                mig_used[gpu_type] = mig_used.get(gpu_type, 0) + int(val)
                            except ValueError:
                                pass
                # Fall back to GresUsed= for non-MIG nodes
                if not any(t in gres_cfg for t in mig_used):
                    mig_used = info.get('gres_used', {})
                    # one configured type (e.g. untyped gpu:8): count every
                    # used GPU against it, whatever type GresUsed reports
                    if len(gres_cfg) == 1:
                        mig_used = {next(iter(gres_cfg)): sum(mig_used.values())}
                detail_parts = []
                for gpu_type, total in sorted(gres_cfg.items()):
                    used = mig_used.get(gpu_type, 0)
                    free = total - used
                    if free == 0:
                        color = "\033[91m"
                    elif free <= 0.5 * total:
                        color = "\033[33m"
                    else:
                        color = "\033[32m"
                    reset = "\033[0m"
                    gray = "\033[90m"
                    white = "\033[97m"
                    detail_parts.append(f"{white}{gpu_type}({reset}{color}{free}{reset}{gray}/{total}{reset}{white}){reset}")
                gpu_detail_str = "  ".join(detail_parts)
                if show_jobs or show_my_jobs:
                    # Jobs are already on the main line; print GPU detail as a sub-line
                    print(out)
                    print(f"   \u2514 {gpu_detail_str}")
                else:
                    out += gpu_detail_str
                    print(out)
            else:
                print(out)
        
        #print queued jobs
        if show_queue:
            # '|'-separated: job names and reasons may contain spaces
            if show_my_jobs:
                result = subprocess.run(["squeue", "-o", "%.12j|%R", "--me" ,"--partition=" + partition], stdout=subprocess.PIPE, universal_newlines=True)
            else:
                result = subprocess.run(["squeue", "-o", "%.12u|%R", "--partition=" + partition], stdout=subprocess.PIPE, universal_newlines=True)

            text = result.stdout
            text = text.split('\n')
            queued_jobs = []
            if len(text) > 1:
                for line in text[1:-1]:
                    line = line.strip()
                    if line != "":
                        user, reason = line.rsplit('|', 1)
                        if reason.startswith("("):
                            queued_jobs.append((user.strip(), reason))
            if len(queued_jobs) > 0:
                out = " ᶫ"
                for user, reason in queued_jobs:
                    #yellow reason
                    reason = reason[1:-1]
                    reason = "\033[33m" + reason + "\033[0m"
                    res = f"{user}({reason})"
                    #italic
                    res = "\033[3m" + res + "\033[0m"
                    out += f"{res}-"
                    
                out = out[:-1] if out.endswith("-") else out
                print(out)

    if show_total:
        #format global info
        int_global_total_cpu = int(global_total_cpu)
        global_total_cpu = "\033[90m" + "/" + str(int_global_total_cpu) + "\033[0m"
        if global_available_cpu == 0:
            global_available_cpu = "\033[91m" + str(global_available_cpu) + "\033[0m"
        elif global_available_cpu <= 0.5 * int_global_total_cpu:
            global_available_cpu = "\033[33m" + str(global_available_cpu) + "\033[0m"
        else:
            global_available_cpu = "\033[32m" + str(global_available_cpu) + "\033[0m"
        global_available_cpu = f"{global_available_cpu}{global_total_cpu}"

        int_global_total_gpu = int(global_total_gpu)
        global_total_gpu = "\033[90m" + "/" + str(int_global_total_gpu) + "\033[0m"
        if global_available_gpu == 0:
            global_available_gpu = "\033[91m" + str(global_available_gpu) + "\033[0m"
        elif global_available_gpu <= 0.5 * int_global_total_gpu:
            global_available_gpu = "\033[33m" + str(global_available_gpu) + "\033[0m"
        else:
            global_available_gpu = "\033[32m" + str(global_available_gpu) + "\033[0m"
        global_available_gpu = f"{global_available_gpu}{global_total_gpu}"

        global_total_mem = "\033[90m" + "/" + str(global_total_mem) + "\033[0m"
        if global_available_mem == 0:
            global_available_mem = "\033[91m" + str(global_available_mem) + "\033[0m"
        else:
            global_available_mem = "\033[32m" + str(global_available_mem) + "\033[0m"
        global_available_mem = f"{global_available_mem}{global_total_mem}"
        global_ = "{:<15}{:<15}{:<30}{:<28}{:<26}".format("TOTAL", f" ", global_available_cpu, global_available_gpu, global_available_mem)
        print(global_)

if __name__ == "__main__":
    main()
