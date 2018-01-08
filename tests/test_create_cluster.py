import itertools
import pytest
import copy

from unittest.mock import MagicMock

from planb.create_cluster import \
    IpAddressPoolDepletedException, \
    add_elastic_ips_to_region, \
    add_nodes_to_regions, \
    collect_seed_nodes, \
    create_user_data_for_ring, \
    create_user_data_template, \
    get_region_ip_iterator, \
    get_subnet_name, \
    make_nodes, \
    seed_iterator


def test_get_subnet_name():
    subnet = {
        'Tags': [{
            'Key': 'Name',
            'Value': 'test-subnet'
        }]
    }
    assert get_subnet_name(subnet) == 'test-subnet'


EU_CENTRAL = {
    'dmz': False,
    'subnets': [
        {
            'name': 'dmz-eu-central-1a',
            'cidr_block': '10.0.0.0/24'
        },
        {
            'name': 'dmz-eu-central-1b',
            'cidr_block': '10.10.0.0/24'
        },
        {
            'name': 'internal-eu-central-1a',
            'cidr_block': '172.31.0.0/24'
        },
        {
            'name': 'internal-eu-central-1b',
            'cidr_block': '172.31.8.0/24'
        }
    ],
    'rings': [
        {
            'size': 5,
        },
        {
            'size': 2,
        }
    ]
}


EU_WEST = {
    'dmz': False,
    'subnets': [
        {
            'name': 'dmz-eu-west-1a',
            'cidr_block': '10.0.0.0/24'
        },
        {
            'name': 'internal-eu-west-1a',
            'cidr_block': '172.31.100.0/24'
        },
        {
            'name': 'internal-eu-west-1b',
            'cidr_block': '172.31.108.0/24',
        },
        {
            'name': 'internal-eu-west-1c',
            'cidr_block': '172.31.116.0/24'
        }
    ],
    'rings': [
        {
            'size': 5,
        }
    ]
}


REGION_RINGS = {
    'eu-central-1': EU_CENTRAL,
    'eu-west-1': EU_WEST
}


expected_central_nodes = [
    # 'PublicIP': None, 'AllocationId': None,
    # 1st ring
    {'_defaultIp': '172.31.0.11', 'PrivateIp': '172.31.0.11',
     'subnet': 'internal-eu-central-1a', 'seed?': True},
    {'_defaultIp': '172.31.8.12', 'PrivateIp': '172.31.8.12',
     'subnet': 'internal-eu-central-1b', 'seed?': True},
    {'_defaultIp': '172.31.0.12', 'PrivateIp': '172.31.0.12',
     'subnet': 'internal-eu-central-1a', 'seed?': True},
    {'_defaultIp': '172.31.8.13', 'PrivateIp': '172.31.8.13',
     'subnet': 'internal-eu-central-1b', 'seed?': False},
    {'_defaultIp': '172.31.0.13', 'PrivateIp': '172.31.0.13',
     'subnet': 'internal-eu-central-1a', 'seed?': False},
    # 2nd ring starts where the 1st left
    {'_defaultIp': '172.31.8.14', 'PrivateIp': '172.31.8.14',
     'subnet': 'internal-eu-central-1b', 'seed?': True},
    {'_defaultIp': '172.31.0.14', 'PrivateIp': '172.31.0.14',
     'subnet': 'internal-eu-central-1a', 'seed?': True},
]


expected_west_nodes = [
    {'_defaultIp': '172.31.100.12', 'PrivateIp': '172.31.100.12',
        'subnet': 'internal-eu-west-1a', 'seed?': True},
    {'_defaultIp': '172.31.108.11', 'PrivateIp': '172.31.108.11',
        'subnet': 'internal-eu-west-1b', 'seed?': True},
    {'_defaultIp': '172.31.116.12',  'PrivateIp': '172.31.116.12',
        'subnet': 'internal-eu-west-1c', 'seed?': True},
    {'_defaultIp': '172.31.100.13',  'PrivateIp': '172.31.100.13',
        'subnet': 'internal-eu-west-1a', 'seed?': False},
    {'_defaultIp': '172.31.108.12', 'PrivateIp': '172.31.108.12',
        'subnet': 'internal-eu-west-1b', 'seed?': False},
]


region_taken_ips = {
    'eu-central-1': set(['172.31.8.11']),
    'eu-west-1':    set(['172.31.100.11', '172.31.116.11'])
}


def test_address_pool_depletion():
    with pytest.raises(IpAddressPoolDepletedException):
        it = get_region_ip_iterator(
            subnets=[
                {
                    'name': 'internal-192-168-1',
                    'cidr_block': '192.168.1.0/30'
                }
            ],
            taken_ips=set(),
            elastic_ips=[],
            dmz=False
        )
        for _ in range(10):
            next(it)

    # should not raise exceptions
    it = get_region_ip_iterator(
        subnets=[
            {
                'name': 'internal-10-0-0',
                'cidr_block': '10.0.0.0/27'
            }
        ],
        taken_ips=set(),
        elastic_ips=[],
        dmz=False
    )
    for _ in range(10):
        next(it)


def test_region_elastic_ip_allocation():
    ec2 = MagicMock()
    elastic_ips = [
        {'PublicIp': '123.45', 'AllocationId': 'a1'},
        {'PublicIp': '123.12', 'AllocationId': 'a2'},
        {'PublicIp': '123.34', 'AllocationId': 'a3'}
    ]
    ec2.allocate_address.side_effect = elastic_ips
    region = {
        'dmz': True,
        'rings': [
            {'size': 1},
            {'size': 2},
        ]
    }
    expected = copy.deepcopy(region)
    expected['elastic_ips'] = elastic_ips

    actual = add_elastic_ips_to_region(ec2, region)
    assert actual == expected

    
def test_make_nodes_one_ring():
    region_rings = copy.deepcopy(REGION_RINGS)
    eu_west = region_rings['eu-west-1']
    eu_west['taken_ips'] = region_taken_ips['eu-west-1']
    eu_west['elastic_ips'] = []
    actual = make_nodes(eu_west)
    assert actual == expected_west_nodes


def test_make_nodes_two_rings():
    region_rings = copy.deepcopy(REGION_RINGS)
    eu_central = region_rings['eu-central-1']
    eu_central['taken_ips'] = region_taken_ips['eu-central-1']
    eu_central['elastic_ips'] = []
    actual = make_nodes(eu_central)
    assert actual == expected_central_nodes


def test_seed_iterator():
    actual = list(seed_iterator(REGION_RINGS['eu-central-1']['rings']))
    expected = [True, True, True, False, False, True, True]
    assert actual == expected


def test_get_region_ip_iterator_elastic_ips():
    elastic_ips = [
         {'PublicIp': '51.1', 'AllocationId': 'a2'},
         {'PublicIp': '51.3', 'AllocationId': 'a4'},
         {'PublicIp': '51.5', 'AllocationId': 'a6'},
         {'PublicIp': '51.7', 'AllocationId': 'a8'}]
    subnets = REGION_RINGS['eu-central-1']['subnets']
    taken_ips = region_taken_ips['eu-central-1']
    ipiter = get_region_ip_iterator(subnets, taken_ips, elastic_ips, True)
    actual = [next(ipiter) for i in range(4)]

    # we want to compare certain keys only
    ignore_keys = set(['PrivateIp', 'PublicIp'])
    for i in actual:
        for ignore in ignore_keys:
            del i[ignore]
    expected = [{'_defaultIp': '51.1', 'AllocationId': 'a2', 'subnet': 'dmz-eu-central-1a'},
                {'_defaultIp': '51.3', 'AllocationId': 'a4', 'subnet': 'dmz-eu-central-1b'},
                {'_defaultIp': '51.5', 'AllocationId': 'a6', 'subnet': 'dmz-eu-central-1a'},
                {'_defaultIp': '51.7', 'AllocationId': 'a8', 'subnet': 'dmz-eu-central-1b'}]

    assert actual == expected


def test_get_region_ip_iterator_remove_taken_ip():
    subnets = REGION_RINGS['eu-central-1']['subnets']
    taken_ips = region_taken_ips['eu-central-1']
    ipiter = get_region_ip_iterator(subnets, taken_ips, [], False)
    actual = [next(ipiter) for i in range(4)]

    expected = [{'_defaultIp': '172.31.0.11', 'subnet': 'internal-eu-central-1a'},
                {'_defaultIp': '172.31.8.12', 'subnet': 'internal-eu-central-1b'},
                {'_defaultIp': '172.31.0.12', 'subnet': 'internal-eu-central-1a'},
                {'_defaultIp': '172.31.8.13', 'subnet': 'internal-eu-central-1b'}]

    # we want to compare certain keys only
    ignore_keys = set(['PrivateIp'])
    for i in actual:
        for ignore in ignore_keys:
            del i[ignore]
    assert actual == expected


def test_add_nodes_to_regions():
    region_rings = copy.deepcopy(REGION_RINGS)
    eu_central = region_rings['eu-central-1']
    eu_central['taken_ips'] = region_taken_ips['eu-central-1']
    eu_central['elastic_ips'] = []
    eu_west = region_rings['eu-west-1']
    eu_west['taken_ips'] = region_taken_ips['eu-west-1']
    eu_west['elastic_ips'] = []

    expected = copy.deepcopy(region_rings)
    expected['eu-central-1']['nodes'] = expected_central_nodes
    expected['eu-west-1']['nodes'] = expected_west_nodes

    actual = add_nodes_to_regions(region_rings)
    assert actual == expected


def test_collect_seed_nodes():
    eu_central = copy.deepcopy(EU_CENTRAL)
    eu_central['nodes'] = expected_central_nodes
    expected = [
        '172.31.0.11', '172.31.8.12', '172.31.0.12',
        '172.31.8.14', '172.31.0.14'
    ]
    assert set(collect_seed_nodes({'eu-central-1': eu_central})) == set(expected)


def test_create_user_data_template():
    cluster = {
        'name': 'hello-world',
        'keystore': b'123',
        'truststore': b'321',
        'admin_password': 'qwerty',
        'docker_image': 'repo/team/artifact:v123',
        'scalyr_key': 'scalyr-key==',
        'scalyr_region': 'eu'
    }
    region_rings = {
        'eu-central-1': {
            'nodes': [
                {'_defaultIp': '12.34.56.78', 'seed?': True},
                {'_defaultIp': '8.8.8.8', 'seed?': False},
                {'_defaultIp': '34.56.78.90', 'seed?': True}
            ]
        }
    }
    expected = {
        'runtime': 'Docker',
        'source': 'repo/team/artifact:v123',
        'application_id': cluster['name'],
        'application_version': 'v123',
        'networking': 'host',
        'ports': {
            '7001': '7001',
            '9042': '9042'
        },
        'environment': {
            'CLUSTER_NAME': cluster['name'],
            'SEEDS': '12.34.56.78,34.56.78.90',
            'KEYSTORE': 'MTIz',
            'TRUSTSTORE': 'MzIx',
            'ADMIN_PASSWORD': 'qwerty',
        },
        'volumes': {
            'ebs': {
                '/dev/xvdf': None
            }
        },
        'mounts': {
            '/var/lib/cassandra': {
                'partition': '/dev/xvdf',
                'options': 'noatime,nodiratime'
            }
        },
        'scalyr_account_key': 'scalyr-key==',
        'scalyr_region': 'eu'
    }
    assert create_user_data_template(cluster, region_rings) == expected


def test_create_user_data_for_ring():
    template = {
        'key': 'unchanged',
        'environment': {
            'OTHER': 'stuff',
        }
    }
    ring = {
        'num_tokens': 1,
        'environment': {
            'EXTRA1': 'value1'
        }
    }
    expected = {
        'key': 'unchanged',
        'environment': {
            'OTHER': 'stuff',
            'NUM_TOKENS': 1,
            'SUBNET_TYPE': 'internal',
            'EXTRA1': 'value1'
        }
    }
    assert create_user_data_for_ring(template, ring, dmz=False) == expected
