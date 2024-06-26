# Nodestat
Nodestat is a command-line tool that shows available resources in a slurm cluster. It displays node statistics such as CPU, GPU, and memory usage, as well as the list of jobs running on each node.

![nodestat](https://github.com/edupooch/nodestat/assets/13384210/cb4cc60c-c0c0-46c7-98d4-76022d24dca3)

## Installation

You can install nodestat directly from the GitHub repository using pip.

```
pip install git+https://github.com/edupooch/nodestat.git
```

## Usage
To display the list of nodes with the number of jobs running on each node, use the -j flag:

```
nodestat -j
```

This will produce an output similar to the following:

```
PARTITION      NODE           CPUS        GPUS      MEM (G)  | JOBS   
a100           node1          0/128       0/8       403/957  | user1(32:2:6G), user1(32:2:6G), user2(64:4:117G)
a100           node2          112/128     2/8       729/957  | user3(8:4:8G), user4(6:1:64G), user5(2:1:100G)
a6000          node3          112/128     7/8       907/957  | user6(16:1:50G)
a6000          node4          64/128      3/8       535/957  | user7(4:1:20G), user7(4:1:20G), user8(16:1:6G), user8(16:1:6G), user9(8:0:6G), user10(16:1:6G)
p6000          node5          38/40       4/4       114/119  | user11(2:0:2G)
rtx2080ti      node6          22/40       5/8       292/478  | user12(12:1:5G), user13(6:2:120G)
rtx2080ti      node7          38/40       7/8       208/238  | user14(2:1:30G)
rtx2080ti_sm   node8          16/24       1/2       60/89    | user8(8:1:29G)
rtx2080ti_sm   node9          20/24       2/2       91/119   | user15(4:0:28G)
rtx2080ti_sm   node10         22/24       1/2       72/89    | user16(2:1:8G)
rtx8000        node11         34/40       2/4       209/239  | user7(2:1:10G), user7(4:1:20G)
```

To show the queued jobs for each partition:
```
nodestat -q
```

To show only current user's jobs
```
nodestat -m
```

To show total available resources
```
nodestat -t
```

To show resources inside a reservation
```
nodestat -r reservation_name
```


## License
This project is licensed under the MIT License - see the LICENSE file for details.
