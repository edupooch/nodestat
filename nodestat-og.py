#!/usr/bin/env python3
import subprocess

def parse_tres(tres_str):
    tres = {}
    for item in tres_str.split(","):
        key, val = item.split("=")
        tres[key] = val
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
                if 'cpu' not in alloc_tres:
                    alloc_tres['cpu'] = '0'
                if 'mem' not in alloc_tres:
                    alloc_tres['mem'] = '0G'
                if 'gres/gpu' not in alloc_tres:
                    alloc_tres['gres/gpu'] = '0'
            node_info[node_name]['alloc_tres'] = alloc_tres

    return node_info

node_info = get_slurm_node_info()
print("{:<15}{:<12}{:>10}{:>10}{:>10}".format("PARTITION", "NODE", "CPUS", "GPUS", "MEM"))

for node_name, info in sorted(node_info.items(), key=lambda x: x[1]['partition']):
    available_cpu = int(info['cfg_tres']['cpu']) - int(info['alloc_tres']['cpu'])
    available_gpu = int(info['cfg_tres']['gres/gpu']) - int(info['alloc_tres']['gres/gpu'])
    available_mem = float(info['cfg_tres']['mem'][0:-1]) - float(info['alloc_tres']['mem'][0:-1])
    available_mem = int(available_mem / 1024)
    available_mem = str(available_mem) + " G"

    print("{:<15}{:<12}{:>10}{:>10}{:>10}".format(info['partition'], node_name, available_cpu, available_gpu, available_mem))

    
    
