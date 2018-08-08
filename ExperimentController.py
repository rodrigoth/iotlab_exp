#!/usr/bin/env python3
import os
import logging
import time
import sys
import zipfile
import numpy as np
import argparse
import subprocess
import json
import re

from iotlabcli import rest, experiment, node
from settings import settings_reader
from random import randint


logging.basicConfig(filename='experiment.log', level=logging.INFO, filemode='w', format='%(asctime)s %(message)s',
                    datefmt='%d/%m/%Y %I:%M:%S %p')

sh = logging.StreamHandler(sys.stdout)
sh.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s : %(message)s')
sh.setFormatter(formatter)
logging.getLogger().addHandler(sh)

sink_firmware_filepath = os.path.join(os.path.dirname(os.path.realpath(__file__)), "firmwares/sink")
node_firmware_filepath = os.path.join(os.path.dirname(os.path.realpath(__file__)), "firmwares/node")
tmux_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts/open_tmux_sessions.sh')


def launch_experiment(deployment_site, number_of_nodes, experiment_time, corridor):
    settings = settings_reader.SettingsReader(deployment_site)

    ids_text = extract_nodes_ids(str(settings.get_parameter(corridor)))
    nodes_ids = []
    for item in ids_text:
        id_begin, id_end = (int(x) for x in item.split("-"))
        nodes_ids.extend(np.arange(id_begin, id_end + 1, 1).tolist())

    json_data = json.loads(experiment.info_experiment(request, site=deployment_site))
    nodes_to_reserve = select_candidates(json_data, nodes_ids, number_of_nodes, deployment_site)

    resources = experiment.exp_resources(nodes_to_reserve)
    experiment_id = json.loads(experiment.submit_experiment(request, '', experiment_time +
                                                            int(settings_reader.SettingsReader('experiment').
                                                            get_parameter("extra_time")), resources))["id"]

    print_log("Starting new Experiment ({})".format(experiment_id))
    print_log("Selected nodes: {}".format(" ".join(nodes_to_reserve)), header=False)

    experiment.wait_experiment(request, experiment_id)
    return experiment_id


def cmd_ssh_forward(experiment_id, deployment_site):
    print_log("Creating tunnel to IoT-Lab")

    nodes_ports_dic = {}

    all_nodes = experiment.get_experiment(request, experiment_id)['nodes']
    starting_port = int(settings_reader.SettingsReader('starting_port').get_parameter("port"))

    seq_ports = np.arange(starting_port, starting_port + len(all_nodes))

    forward_cmd = []

    for counter, node in enumerate(all_nodes):
        forward_cmd.append(" -L {}:{}:{}".format(seq_ports[counter], node,
                                                 settings_reader.SettingsReader(deployment_site).get_parameter(
                                                     "listening_port")))
        nodes_ports_dic[node] = seq_ports[counter]

    forward_cmd = "".join(forward_cmd)

    ssh_tunnel_command = "ssh -T {}@{}.iot-lab.info {} ".format(
        settings_reader.SettingsReader("iot-lab-account").get_parameter(
            "user"), deployment_site, forward_cmd)

    pass_arg = [tmux_script_path, "ssh_forward", ssh_tunnel_command]
    subprocess.check_call(pass_arg)

    return nodes_ports_dic


def cmd_pseudo_tty(nodes_ports_dic):
    print_log("Creating pseudo ports")
    if nodes_ports_dic:
        i = 0
        for node, port in nodes_ports_dic.items():
            socat_command = ("sudo socat TCP4:localhost:%s " % port + "pty,link=/dev/ttyUSB-pseudo-%s,raw" % i)
            pass_arg = [tmux_script_path, "m3-" + str(extract_node_id(node)), socat_command]
            subprocess.check_call(pass_arg)
            i += 1
            time.sleep(1)


def run_openvisualizer():
    print_log("Loading OpenVisualizer")
    pass_arg = [tmux_script_path, "OpenVisualizer",
                "cd {};sudo scons runweb".format(
                    settings_reader.SettingsReader('openwsn-sw').get_parameter("sw_openvisualizer_path"))]
    subprocess.check_call(pass_arg)


def close_openvisualizer():
    print_log("Closing OpenVisualizer")
    pass_arg = [tmux_script_path, "OpenVisualizer", "quit"]
    subprocess.check_call(pass_arg)


def kill_tmux_session():
    print_log("Killing tmux sessions")
    os.system("pkill -f tmux")


def print_log(text,header=True):
    if header:
        logging.info("********************* {} *********************".format(text))
    else:
        logging.info("{}".format(text))
    logging.info("")
    logging.info("")


def extract_node_id(text):
    find = re.compile(r"\-([^\.]+)\.")
    return int(re.search(find, text).group(1))


def extract_nodes_ids(text):
    return re.findall(r"\[(.*?)\]",text)


def select_candidates(json_data, nodes_ids, total_nodes, deployment_site, arch='m3', add_fixed_nodes=False):
    selected_nodes = []
    exclude_nodes = settings_reader.SettingsReader(deployment_site).get_parameter("excluded_nodes").split(",")

    exclude_ids = [extract_node_id(i) for i in exclude_nodes]

    for element in json_data["items"]:
        if arch in element['archi'] and element['state'] not in ["Busy","Suspected"]:
            if extract_node_id(element['network_address']) in nodes_ids and extract_node_id(element['network_address']) \
                    not in exclude_ids:
                selected_nodes.append((element['network_address']))

    selected_nodes = np.random.choice(selected_nodes, total_nodes, replace=False).tolist()

    if add_fixed_nodes:
        settings = settings_reader.SettingsReader(deployment_site)
        fixed_nodes = settings.get_parameter("fixed_nodes").split(",")
        selected_nodes.extend(fixed_nodes)
    return selected_nodes


def flash_nodes(experiment_id):
    all_nodes = experiment.get_experiment(request, experiment_id)['nodes']

    np.random.shuffle(all_nodes)

    # sink is always the first element
    sink = [all_nodes[0]]
    nodes = all_nodes[1:len(all_nodes)]

    print_log("Sink: {}".format(" ".join(sink)),header=False)
    print_log("Nodes: {}".format(" ".join(nodes)),header=False)

    print_log("Flashing nodes", header=False)
    node.node_command(request, 'update', experiment_id, nodes, node_firmware_filepath)
    # flash again
    node.node_command(request, 'update', experiment_id, nodes, node_firmware_filepath)

    print_log("Flashing sink", header=False)
    node.node_command(request, 'update', experiment_id, sink, sink_firmware_filepath)
    # flash again
    node.node_command(request, 'update', experiment_id, sink, sink_firmware_filepath)


def remove_older_firmwares():
    if os.path.exists(sink_firmware_filepath):
        os.remove(sink_firmware_filepath)

    if os.path.exists(node_firmware_filepath):
        os.remove(node_firmware_filepath)


def build_firwmare(script, target_device):
    os.system('cd {};{}'.format(settings_reader.SettingsReader('openwsn-fw').get_parameter("fw_path"), script))
    os.system("cp {} {}".format(settings_reader.SettingsReader('openwsn-fw').get_parameter("fw_firmware_path"),
                                os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                             "firmwares/{}".format(target_device))))


def abort_experiment(experiment_id):
    json.loads(experiment.stop_experiment(request, experiment_id))


def zip_log_files(experiment):
    sw_log_path = settings_reader.SettingsReader('openwsn-sw').get_parameter("sw_log_path")
    log_zip = zipfile.ZipFile(sw_log_path + str(experiment) + ".zip", 'w')
    for folder, subfolders, files in os.walk(sw_log_path):
        for file in files:
            if file.startswith('openVisualizer.log'):
                log_zip.write(os.path.join(folder, file), os.path.relpath(os.path.join(folder, file), sw_log_path),
                              compress_type=zipfile.ZIP_DEFLATED)

        log_zip.close()

        for file in files:
            if file.startswith('openVisualizer.log'):
                os.remove(os.path.join(sw_log_path, file))


def main(experiments, experiment_time, number_of_nodes, site, corridor):
    """
    The time between steps is totally experiment dependent. It may need to adjust them until I fix this :-)
    """
    for exp_counter in experiments:
        pan_id = randint(1, 200)
        experiment_id = launch_experiment(site, number_of_nodes, experiment_time, corridor)

        time.sleep(int(settings_reader.SettingsReader("experiment").get_parameter("step_time")))

        nodes_ports = cmd_ssh_forward(experiment_id, site)
        time.sleep(int(settings_reader.SettingsReader("experiment").get_parameter("step_time")))

        cmd_pseudo_tty(nodes_ports)
        time.sleep(int(settings_reader.SettingsReader("experiment").get_parameter("step_time")))

        remove_older_firmwares()

        run_openvisualizer()

        build_script = str(settings_reader.SettingsReader("build").get_parameter("build_command_node")).format(pan_id,
                                                                                                               exp_counter)
        print_log("Experiment {}".format(exp_counter), header=False)

        print_log("Building node firmware ({})".format(build_script), header=False)
        build_firwmare(build_script, "node")

        build_script = str(settings_reader.SettingsReader("build").get_parameter("build_command_sink")).format(pan_id,
                                                                                                               exp_counter)

        print_log("Building sink firmware ({})".format(build_script), header=False)

        build_firwmare(build_script, "sink")

        print_log("Waiting OpenVisualizer")

        time.sleep(int(settings_reader.SettingsReader("experiment").get_parameter("openvisualizer_time")))

        flash_nodes(experiment_id)

        time.sleep(experiment_time * 60)

        # ending the current experiment
        close_openvisualizer()
        kill_tmux_session()
        abort_experiment(experiment_id)
        zip_log_files(exp_counter)
        # wait before starting the next experiment
        time.sleep(int(settings_reader.SettingsReader("experiment").get_parameter("openvisualizer_time")))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiments', type=str, required=True)
    parser.add_argument('--experiment_time', type=int, required=True)
    parser.add_argument('--number_of_nodes', type=int, required=True)
    parser.add_argument('--corridor', type=str, required=True, choices=['a', 'b', 'c', 'd'])
    parser.add_argument('--site', type=str, required=True, choices=['grenoble'])  # add the others
    args = parser.parse_args()

    request = rest.Api(username=settings_reader.SettingsReader('iot-lab-account').get_parameter('user'),
                     password=settings_reader.SettingsReader('iot-lab-account').get_parameter('password'))

    if not rest.Api.check_credential(request):
        raise ValueError("Invalid credentials!!")

    main(args.experiments.split(','), args.experiment_time, args.number_of_nodes, args.site, args.corridor)
