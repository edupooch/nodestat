#!/bin/bash
#SBATCH -t 1-00:00:00
#SBATCH -p rtx2080ti_sm
#SBATCH --job-name="sleep"
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1

sleep 60