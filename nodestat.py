#!/usr/bin/env python3
import subprocess
import argparse
import math
import re 


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

def get_slurm_node_info():
    node_info = {}
    command = "scontrol show node"
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
    
    return node_info

def parse_mem(mem_str):
    if mem_str.endswith("M"):
        mem = float(mem_str[:-1]) / 1000
    elif mem_str.endswith("K"):
        mem = float(mem_str[:-1]) / 1000 / 1000
    else:
        mem = float(mem_str[:-1])
    return int(mem)

def get_slurm_jobs():
    result = subprocess.run(["scontrol", "show", "job"], stdout=subprocess.PIPE, universal_newlines=True)
    job_str = result.stdout.split('\n\n')
    job_info = {}
    for job in job_str:
        job = job.strip()
        if len(job.split('JobId=')) == 1:
            continue
        job_id = job.split('JobId=')[1].split(' ')[0]
        job_info[job_id] = {}
        job_info[job_id]['nodes'] = job.split(' NodeList=')[1].split(' ')[0].strip().split(',')
        job_info[job_id]['state'] = job.split('JobState=')[1].split(' ')[0]
        job_info[job_id]['user'] = job.split('UserId=')[1].split(' ')[0].split('(')[0]
        #TRES 
        tres_str = job.split('AllocTRES=')[1].split(' ')[0]
        if 'null'in tres_str:
            tres_str = 'cpu=0,mem=0G,gres/gpu=0'
        tres = parse_tres(tres_str)
        job_info[job_id]['tres'] = tres
        
    return job_info

def get_node_default_values():
    default = {}
    with open("/etc/slurm/slurm.conf", "r") as f:
        lines = f.readlines()
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
        nodes_str = nodes_line[0].split('=')[1].strip()
        nodes = []
        
        if '[' in nodes_str:
            base_name = nodes_str.split('[')[0]
            ranges = nodes_str.split('[')[1].split(']')[0].split(',')
            for item in ranges:
                if '-' in item:
                    start, end = map(int, item.split('-'))
                    nodes.extend([f"{base_name}{i}" for i in range(start, end + 1)])
                else:
                    nodes.append(f"{base_name}{item}")
        else:
            nodes = nodes_str.split(',')
        
        return nodes
    
    return []
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--jobs", help="show active jobs on the nodes", action="store_true")
    parser.add_argument("-m", "--me", help="show only my jobs", action="store_true")
    parser.add_argument("-q", "--queue", help="show jobs in the queue", action="store_true")
    parser.add_argument("-t", "--total", help="show total resources", action="store_true")
    parser.add_argument("-r", "--reservation", help="show resources inside reservation")

    args = parser.parse_args()
    show_jobs = args.jobs
    show_my_jobs = args.me
    show_queue = args.queue
    show_total = args.total
    reservation_name = args.reservation

    node_info = get_slurm_node_info()
    if show_jobs or show_my_jobs:
        job_info = get_slurm_jobs()
        default_values = get_node_default_values()

    if reservation_name:
        reservation_nodes = get_nodes_in_reservation(reservation_name)
        node_info = {node: info for node, info in node_info.items() if node in reservation_nodes}

    print("{:<15}{:<15}{:<12}{:<10}{:<8}{:<10}".format("PARTITION", "NODE", "CPUS", "GPUS", "MEM (G)", " | JOBS" if show_jobs or show_my_jobs else " "))

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
            total_cpu = int(info['cfg_tres']['cpu'])    
            global_available_cpu += available_cpu
            global_total_cpu += total_cpu

            total_cpu = "\033[90m" + "/" + str(total_cpu) + "\033[0m"
            if available_cpu == 0:
                available_cpu = "\033[91m" + str(available_cpu) + "\033[0m"
            else:
                available_cpu = "\033[32m" + str(available_cpu) + "\033[0m"
            available_cpu = f"{available_cpu}{total_cpu}"

            available_gpu = int(info['cfg_tres']['gres/gpu']) - int(info['alloc_tres']['gres/gpu'])
            total_gpu = int(info['cfg_tres']['gres/gpu'])
            global_available_gpu += available_gpu
            global_total_gpu += total_gpu
            total_gpu = "\033[90m" + "/" + str(total_gpu) + "\033[0m"
            if available_gpu == 0:
                available_gpu = "\033[91m" + str(available_gpu) + "\033[0m"
            else:
                available_gpu = "\033[32m" + str(available_gpu) + "\033[0m"
            
            # on cpu servers replace 0/0 with -
            if int(info['cfg_tres']['gres/gpu']) == 0:
                available_gpu =  "\033[91m" + " " + "\033[0m"
                total_gpu = "\033[90m" + "-" + " " + "\033[0m"        

            available_gpu = f"{available_gpu}{total_gpu}"

            available_mem = parse_mem(info['cfg_tres']['mem']) - parse_mem(info['alloc_tres']['mem'])
            total_mem = parse_mem(info['cfg_tres']['mem'])
            global_available_mem += available_mem
            global_total_mem += total_mem

            total_mem = "\033[90m" + "/" + str(total_mem) + "\033[0m"
            if available_mem == 0:
                available_mem = "\033[91m" + str(available_mem) + "\033[0m"
            else:
                available_mem = "\033[32m" + str(available_mem) + "\033[0m"
    
            available_mem = f"{available_mem}{total_mem}"
            state = info['state']
            
            if state != 'IDLE' and state != 'MIXED' and state != 'ALLOCATED':
                if not reservation_name:
                    if "RESERVED" in state:
                        available_cpu = "\033[90m"  + "RESERVED" + "\033[0m" + "\033[32m" + "" + "\033[0m"
                    else:
                        available_cpu = "\033[90m"  + "SUSPENDED" + "\033[0m" + "\033[32m" + "" + "\033[0m"
                    
                    available_gpu = "\033[91m"  + " " + "\033[0m" + "\033[32m" + "" + "\033[0m"
                    available_mem = "\033[91m"  + " " + "\033[0m" + "\033[32m" + "" + "\033[0m"
    
            out = "{:<15}{:<15}{:<30}{:<28}{:<26}{}".format(info['partition'], node_name, available_cpu, available_gpu, available_mem, " | " if show_jobs or show_my_jobs else " ")
            if show_jobs or show_my_jobs:
                if show_jobs:
                    result = subprocess.run(["squeue", "-o", "%.12u,%C,%b,%m,%i", "--nodelist=" + node_name], stdout=subprocess.PIPE, universal_newlines=True)
                if show_my_jobs:
                    result = subprocess.run(["squeue", "-o", "%.12j,%C,%b,%m,%i", "--me", "--nodelist=" + node_name], stdout=subprocess.PIPE, universal_newlines=True)

                text = result.stdout
                text = text.split('\n')

                if len(text) > 1:
                    for line in text[1:-1]:
                        line = line.strip()
                        if line != "":
                            values = line.split(',')
                            user = values[0]
                            cpu = values[1]
                            gpu = values[2]
                            mem = values[3]
                            jobid = values[4]
                            jobid = jobid.split('_')[0]
                            gpu = job_info[jobid]['tres']['gres/gpu']
                            mem = job_info[jobid]['tres']['mem']
                            mem = parse_mem(mem)

                            total_gpu = info['cfg_tres']['gres/gpu']
                            recommended_cpu = default_values[node_name]['DefCpuPerGPU'] * int(gpu) if int(gpu) > 0 else 2                
                            recommended_mem = parse_mem(str(default_values[node_name]['DefMemPerCPU'] * int(cpu)) + "M")
                            
                            if int(cpu) <= recommended_cpu:
                                cpu = "\033[33m" + cpu + "\033[0m"
                            else: 
                                cpu = "\033[91m" + cpu + "\033[0m"
                            
                            if mem <= recommended_mem:
                                mem = "\033[33m" + str(mem) + "G" + "\033[0m"
                            else:
                                mem = "\033[91m" + str(mem) + "G" + "\033[0m"

                            if gpu == "0": #gray
                                gpu = "\033[90m" + gpu + "\033[0m"
                            else:
                                gpu = "\033[33m" + gpu + "\033[0m"

                            #bold user 
                            user = "\033[1m" + user + "\033[0m"
                        
                            res = f"{cpu}:{gpu}:{mem}"

                            out += f"{user}({res}), "
                    out = out[:-2] if out.endswith(", ") else out
            print(out)
        
        #print queued jobs
        if show_queue:
            result = subprocess.run(["squeue", "-o", " %.12u %i %R", "--partition=" + partition], stdout=subprocess.PIPE, universal_newlines=True)
            if show_my_jobs:
                result = subprocess.run(["squeue", "-o", " %.12j %i %R", "--me" ,"--partition=" + partition], stdout=subprocess.PIPE, universal_newlines=True)
            
            text = result.stdout
            text = text.split('\n')
            queued_jobs = []
            if len(text) > 1:
                for line in text[1:-1]:
                    line = line.strip()
                    if line != "":
                        reason = line.split()[2]
                        if reason.startswith("("):
                            queued_jobs.append(line)
            if len(queued_jobs) > 0:
                out = " ᶫ"
                for line in queued_jobs:
                    info = line.split()
                    user = info[0]
                    jobid = info[1].split('_')[0]
                    reason = " ".join(info[2:])
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
        global_total_cpu = "\033[90m" + "/" + str(global_total_cpu) + "\033[0m"
        if global_available_cpu == 0:
            global_available_cpu = "\033[91m" + str(global_available_cpu) + "\033[0m"
        else:
            global_available_cpu = "\033[32m" + str(global_available_cpu) + "\033[0m"
        global_available_cpu = f"{global_available_cpu}{global_total_cpu}"

        global_total_gpu = "\033[90m" + "/" + str(global_total_gpu) + "\033[0m"
        if global_available_gpu == 0:
            global_available_gpu = "\033[91m" + str(global_available_gpu) + "\033[0m"
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