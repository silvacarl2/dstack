import re
from typing import Any, List
import warnings

from google.cloud.storage import Bucket
from google.cloud import compute_v1
import google.api_core.exceptions
import yaml

from dstack.backend.gcp import storage, utils as gcp_utils
from dstack.core.runners import Runner
from dstack.backend.aws.runners import _serialize_runner, _unserialize_runner
from dstack.backend.gcp.config import GCPConfig


def create_runner(bucket: Bucket, runner: Runner):
    runner_filepath = f"runners/{runner.runner_id}.yaml"
    storage.put_object(bucket, runner_filepath, yaml.dump(_serialize_runner(runner)))


def update_runner(bucket: Bucket, runner: Runner):
    # Simply override the existing runner
    create_runner(bucket, runner)


def get_runner(bucket: Bucket, runner_id: str) -> Runner:
    runner_filepath = f"runners/{runner_id}.yaml"
    obj = storage.read_object(bucket, runner_filepath)
    return _unserialize_runner(yaml.load(obj, yaml.FullLoader))


def delete_runner(bucket: Bucket, runner_id: str):
    runner_filepath = f"runners/{runner_id}.yaml"
    storage.delete_object(bucket, runner_filepath)


def launch_runner(gcp_config: GCPConfig, bucket: Bucket, runner: Runner) -> str:
    instance = _launch_instance(
        project_id=gcp_config.project_id,
        zone=gcp_config.zone,
        image_name="stgn-dstack-5",
        instance_name=_get_instance_name(runner),
    )
    return instance.name


def _get_instance_name(runner: Runner) -> str:
    # TODO support multiple jobs per run
    return f"dstack-{runner.job.run_name}"


def _launch_instance(project_id: str, zone: str, image_name: str, instance_name: str) -> compute_v1.Instance:
    disk = _disk_from_image(
        disk_type=f"zones/{zone}/diskTypes/pd-balanced",
        disk_size_gb=20,
        boot=True,
        source_image=f"projects/dstack/global/images/{image_name}",
        auto_delete=False,
    )
    instance = _create_instance(
        project_id=project_id,
        zone=zone,
        instance_name=instance_name,
        disks=[disk],
    )
    return instance


def _disk_from_image(
    disk_type: str,
    disk_size_gb: int,
    boot: bool,
    source_image: str,
    auto_delete: bool = True,
) -> compute_v1.AttachedDisk:
    """
    Create an AttachedDisk object to be used in VM instance creation. Uses an image as the
    source for the new disk.

    Args:
         disk_type: the type of disk you want to create. This value uses the following format:
            "zones/{zone}/diskTypes/(pd-standard|pd-ssd|pd-balanced|pd-extreme)".
            For example: "zones/us-west3-b/diskTypes/pd-ssd"
        disk_size_gb: size of the new disk in gigabytes
        boot: boolean flag indicating whether this disk should be used as a boot disk of an instance
        source_image: source image to use when creating this disk. You must have read access to this disk. This can be one
            of the publicly available images or an image from one of your projects.
            This value uses the following format: "projects/{project_name}/global/images/{image_name}"
        auto_delete: boolean flag indicating whether this disk should be deleted with the VM that uses it

    Returns:
        AttachedDisk object configured to be created using the specified image.
    """
    boot_disk = compute_v1.AttachedDisk()
    initialize_params = compute_v1.AttachedDiskInitializeParams()
    initialize_params.source_image = source_image
    initialize_params.disk_size_gb = disk_size_gb
    initialize_params.disk_type = disk_type
    boot_disk.initialize_params = initialize_params
    # Remember to set auto_delete to True if you want the disk to be deleted when you delete
    # your VM instance.
    boot_disk.auto_delete = auto_delete
    boot_disk.boot = boot
    return boot_disk


def _create_instance(
    project_id: str,
    zone: str,
    instance_name: str,
    disks: List[compute_v1.AttachedDisk],
    machine_type: str = "n1-standard-1",
    network_link: str = "global/networks/default",
    subnetwork_link: str = None,
    internal_ip: str = None,
    external_access: bool = False,
    external_ipv4: str = None,
    accelerators: List[compute_v1.AcceleratorConfig] = None,
    preemptible: bool = False,
    spot: bool = False,
    instance_termination_action: str = "STOP",
    custom_hostname: str = None,
    delete_protection: bool = False,
) -> compute_v1.Instance:
    """
    Send an instance creation request to the Compute Engine API and wait for it to complete.

    Args:
        project_id: project ID or project number of the Cloud project you want to use.
        zone: name of the zone to create the instance in. For example: "us-west3-b"
        instance_name: name of the new virtual machine (VM) instance.
        disks: a list of compute_v1.AttachedDisk objects describing the disks
            you want to attach to your new instance.
        machine_type: machine type of the VM being created. This value uses the
            following format: "zones/{zone}/machineTypes/{type_name}".
            For example: "zones/europe-west3-c/machineTypes/f1-micro"
        network_link: name of the network you want the new instance to use.
            For example: "global/networks/default" represents the network
            named "default", which is created automatically for each project.
        subnetwork_link: name of the subnetwork you want the new instance to use.
            This value uses the following format:
            "regions/{region}/subnetworks/{subnetwork_name}"
        internal_ip: internal IP address you want to assign to the new instance.
            By default, a free address from the pool of available internal IP addresses of
            used subnet will be used.
        external_access: boolean flag indicating if the instance should have an external IPv4
            address assigned.
        external_ipv4: external IPv4 address to be assigned to this instance. If you specify
            an external IP address, it must live in the same region as the zone of the instance.
            This setting requires `external_access` to be set to True to work.
        accelerators: a list of AcceleratorConfig objects describing the accelerators that will
            be attached to the new instance.
        preemptible: boolean value indicating if the new instance should be preemptible
            or not. Preemptible VMs have been deprecated and you should now use Spot VMs.
        spot: boolean value indicating if the new instance should be a Spot VM or not.
        instance_termination_action: What action should be taken once a Spot VM is terminated.
            Possible values: "STOP", "DELETE"
        custom_hostname: Custom hostname of the new VM instance.
            Custom hostnames must conform to RFC 1035 requirements for valid hostnames.
        delete_protection: boolean value indicating if the new virtual machine should be
            protected against deletion or not.
    Returns:
        Instance object.
    """
    instance_client = compute_v1.InstancesClient()

    # Use the network interface provided in the network_link argument.
    network_interface = compute_v1.NetworkInterface()
    network_interface.name = network_link
    if subnetwork_link:
        network_interface.subnetwork = subnetwork_link

    if internal_ip:
        network_interface.network_i_p = internal_ip

    if external_access:
        access = compute_v1.AccessConfig()
        access.type_ = compute_v1.AccessConfig.Type.ONE_TO_ONE_NAT.name
        access.name = "External NAT"
        access.network_tier = access.NetworkTier.PREMIUM.name
        if external_ipv4:
            access.nat_i_p = external_ipv4
        network_interface.access_configs = [access]

    # Collect information into the Instance object.
    instance = compute_v1.Instance()
    instance.network_interfaces = [network_interface]
    instance.name = instance_name
    instance.disks = disks
    if re.match(r"^zones/[a-z\d\-]+/machineTypes/[a-z\d\-]+$", machine_type):
        instance.machine_type = machine_type
    else:
        instance.machine_type = f"zones/{zone}/machineTypes/{machine_type}"

    if accelerators:
        instance.guest_accelerators = accelerators

    if preemptible:
        # Set the preemptible setting
        warnings.warn(
            "Preemptible VMs are being replaced by Spot VMs.", DeprecationWarning
        )
        instance.scheduling = compute_v1.Scheduling()
        instance.scheduling.preemptible = True

    if spot:
        # Set the Spot VM setting
        instance.scheduling = compute_v1.Scheduling()
        instance.scheduling.provisioning_model = (
            compute_v1.Scheduling.ProvisioningModel.SPOT.name
        )
        instance.scheduling.instance_termination_action = instance_termination_action

    if custom_hostname is not None:
        # Set the custom hostname for the instance
        instance.hostname = custom_hostname

    if delete_protection:
        # Set the delete protection bit
        instance.deletion_protection = True

    # Prepare the request to insert an instance.
    request = compute_v1.InsertInstanceRequest()
    request.zone = zone
    request.project = project_id
    request.instance_resource = instance

    # Wait for the create operation to complete.
    print(f"Creating the {instance_name} instance in {zone}...")

    operation = instance_client.insert(request=request)

    gcp_utils.wait_for_extended_operation(operation, "instance creation")

    print(f"Instance {instance_name} created.")
    return instance_client.get(project=project_id, zone=zone, instance=instance_name)


def stop_runner(gcp_config: GCPConfig, runner: Runner):
    _delete_instance(
        instance_name=_get_instance_name(runner),
        project_id=gcp_config.project_id,
        zone=gcp_config.zone,
    )


def _delete_instance(project_id: str, zone: str, instance_name: str):
    delete_request = compute_v1.DeleteInstanceRequest(
        instance=instance_name,
        project=project_id,
        zone=zone,
    )
    client = compute_v1.InstancesClient()
    try:
        client.delete(delete_request)
    except google.api_core.exceptions.NotFound:
        pass


def main():
    project_id = "dstack"
    image_name = "stgn-dstack-5"
    zone= "us-central1-a"
    # _launch_instance(project_id, zone, image_name, image_name)
    _delete_instance(project_id, zone, 'stgn-dstack-5')


if __name__ == "__main__":
    main()
