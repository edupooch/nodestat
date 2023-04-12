#!/usr/bin/env python3
import subprocess
import argparse
import math

parser = argparse.ArgumentParser()
parser.add_argument("-j", "--jobs", help="show active jobs on the nodes", action="store_true")
parser.add_argument("-m", "--me", help="show only my jobs", action="store_true")
parser.add_argument("-q", "--queue", help="show jobs in the queue", action="store_true")

show_jobs = parser.parse_args().jobs
show_my_jobs = parser.parse_args().me
show_queue = parser.parse_args().queue

assert not (show_jobs and show_my_jobs), "You can't use -j and --me at the same time"

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

def get_slutm_jobs():
    result = subprocess.run(["scontrol", "show", "job"], stdout=subprocess.PIPE, universal_newlines=True)
    job_str = result.stdout.split('\n\n')
    job_info = {}
    for job in job_str:
        job = job.strip()
        if job == '':
            continue
        job_id = job.split('JobId=')[1].split(' ')[0]
        job_info[job_id] = {}
        job_info[job_id]['nodes'] = job.split(' NodeList=')[1].split(' ')[0].strip().split(',')
        job_info[job_id]['state'] = job.split('JobState=')[1].split(' ')[0]
        job_info[job_id]['user'] = job.split('UserId=')[1].split(' ')[0].split('(')[0]
        #TRES
        tres_str = job.split('TRES=')[1].split(' ')[0]
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
            if "DefMemPerCPU=" in line and "DefCpuPerGPU=" in line:
                mem = int(line.split("DefMemPerCPU=")[1].split(" ")[0])
                cpu = int(line.split("DefCpuPerGPU=")[1].split(" ")[0])
                for node_name in node_names:
                    default[node_name] = {"DefMemPerCPU": mem, "DefCpuPerGPU": cpu}
    return default

node_info = get_slurm_node_info()
if show_jobs or show_my_jobs:
    job_info = get_slutm_jobs()
    default_values = get_node_default_values()

print("{:<15}{:<15}{:<12}{:<10}{:<8}{:<10}".format("PARTITION", "NODE", "CPUS", "GPUS", "MEM (G)", " | JOBS" if show_jobs or show_my_jobs else " "))

partitions = set([info['partition'] for node_name, info in node_info.items()])
partitions = sorted(partitions)

for partition in partitions:
    info_partition = [x for x in node_info.items() if x[1]['partition'] == partition]
    for node_name, info in info_partition:
        available_cpu = int(info['cfg_tres']['cpu']) - int(info['alloc_tres']['cpu'])
        total_cpu = int(info['cfg_tres']['cpu'])
        total_cpu = "\033[90m" + "/" + str(total_cpu) + "\033[0m"
        if available_cpu == 0:
            available_cpu = "\033[91m" + str(available_cpu) + "\033[0m"
        else:
            available_cpu = "\033[32m" + str(available_cpu) + "\033[0m"
        available_cpu = f"{available_cpu}{total_cpu}"

        available_gpu = int(info['cfg_tres']['gres/gpu']) - int(info['alloc_tres']['gres/gpu'])
        total_gpu = int(info['cfg_tres']['gres/gpu'])
        total_gpu = "\033[90m" + "/" + str(total_gpu) + "\033[0m"
        if available_gpu == 0:
            available_gpu = "\033[91m" + str(available_gpu) + "\033[0m"
        else:
            available_gpu = "\033[32m" + str(available_gpu) + "\033[0m"
        available_gpu = f"{available_gpu}{total_gpu}"

        available_mem = parse_mem(info['cfg_tres']['mem']) - parse_mem(info['alloc_tres']['mem'])
        total_mem = parse_mem(info['cfg_tres']['mem'])
        total_mem = "\033[90m" + "/" + str(total_mem) + "\033[0m"
        if available_mem == 0:
            available_mem = "\033[91m" + str(available_mem) + "\033[0m"
        else:
            available_mem = "\033[32m" + str(available_mem) + "\033[0m"

        available_mem = f"{available_mem}{total_mem}"
        state = info['state']

        if state != 'IDLE' and state != 'MIXED' and state != 'ALLOCATED':
            available_cpu = "\033[90m"  + "SUSPENDED" + "\033[0m" + "\033[32m" + "" + "\033[0m"
            available_gpu = "\033[91m"  + " " + "\033[0m" + "\033[32m" + "" + "\033[0m"
            available_mem = "\033[91m"  + " " + "\033[0m" + "\033[32m" + "" + "\033[0m"

        out = "{:<15}{:<15}{:<30}{:<28}{:<26}{}".format(info['partition'], node_name, available_cpu, available_gpu, available_mem, " | " if show_jobs or show_my_jobs else " ")
        if show_jobs or show_my_jobs:
            if show_jobs:
                result = subprocess.run(["squeue", "-o", " %.12u %C %b %m %i", "--nodelist=" + node_name], stdout=subprocess.PIPE, universal_newlines=True)
            if show_my_jobs:
                result = subprocess.run(["squeue", "-o", " %.12j %C %b %m %i", "--me" ,"--nodelist=" + node_name], stdout=subprocess.PIPE, universal_newlines=True)
            
            text = result.stdout
            text = text.split('\n')

            if len(text) > 1:
                for line in text[1:-1]:
                    line = line.strip()
                    if line != "":
                        user, cpu, gpu, mem, jobid = line.split()
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
                    user, jobid, reason = line.split()
                    if reason.startswith("("):
                        queued_jobs.append(line)
        if len(queued_jobs) > 0:
            out = " ᶫ"
            for line in queued_jobs:
                user, jobid, reason = line.split()
                #yellow reason
                reason = reason[1:-1]
                reason = "\033[33m" + reason + "\033[0m"
                res = f"{user}({reason})"
                #italic
                res = "\033[3m" + res + "\033[0m"
                out += f"{res}, "
            
            out = out[:-2] if out.endswith(", ") else out
            print(out)
                        