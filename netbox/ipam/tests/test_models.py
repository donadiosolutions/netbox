from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from netaddr import IPNetwork, IPSet
from utilities.data import string_to_ranges

from dcim.models import Site, SiteGroup
from ipam.choices import *
from ipam.models import *


class TestAggregate(TestCase):

    def test_get_utilization(self):
        rir = RIR.objects.create(name='RIR 1', slug='rir-1')
        aggregate = Aggregate(prefix=IPNetwork('10.0.0.0/8'), rir=rir)
        aggregate.save()

        # 25% utilization
        Prefix.objects.bulk_create((
            Prefix(prefix=IPNetwork('10.0.0.0/12')),
            Prefix(prefix=IPNetwork('10.16.0.0/12')),
            Prefix(prefix=IPNetwork('10.32.0.0/12')),
            Prefix(prefix=IPNetwork('10.48.0.0/12')),
        ))
        self.assertEqual(aggregate.get_utilization(), 25)

        # 50% utilization
        Prefix.objects.bulk_create((
            Prefix(prefix=IPNetwork('10.64.0.0/10')),
        ))
        self.assertEqual(aggregate.get_utilization(), 50)

        # 100% utilization
        Prefix.objects.bulk_create((
            Prefix(prefix=IPNetwork('10.128.0.0/9')),
        ))
        self.assertEqual(aggregate.get_utilization(), 100)


class TestIPRange(TestCase):

    def test_overlapping_range(self):
        iprange_192_168 = IPRange.objects.create(
            start_address=IPNetwork('192.168.0.1/22'), end_address=IPNetwork('192.168.0.49/22')
        )
        iprange_192_168.clean()
        iprange_3_1_99 = IPRange.objects.create(
            start_address=IPNetwork('1.2.3.1/24'), end_address=IPNetwork('1.2.3.99/24')
        )
        iprange_3_1_99.clean()
        iprange_3_100_199 = IPRange.objects.create(
            start_address=IPNetwork('1.2.3.100/24'), end_address=IPNetwork('1.2.3.199/24')
        )
        iprange_3_100_199.clean()
        iprange_3_200_255 = IPRange.objects.create(
            start_address=IPNetwork('1.2.3.200/24'), end_address=IPNetwork('1.2.3.255/24')
        )
        iprange_3_200_255.clean()
        iprange_4_1_99 = IPRange.objects.create(
            start_address=IPNetwork('1.2.4.1/24'), end_address=IPNetwork('1.2.4.99/24')
        )
        iprange_4_1_99.clean()
        iprange_4_200 = IPRange.objects.create(
            start_address=IPNetwork('1.2.4.200/24'), end_address=IPNetwork('1.2.4.255/24')
        )
        iprange_4_200.clean()

        # Overlapping range entirely within existing
        with self.assertRaises(ValidationError):
            iprange_3_123_124 = IPRange.objects.create(
                start_address=IPNetwork('1.2.3.123/26'), end_address=IPNetwork('1.2.3.124/26')
            )
            iprange_3_123_124.clean()

        # Overlapping range starting within existing
        with self.assertRaises(ValidationError):
            iprange_4_98_101 = IPRange.objects.create(
                start_address=IPNetwork('1.2.4.98/24'), end_address=IPNetwork('1.2.4.101/24')
            )
            iprange_4_98_101.clean()

        # Overlapping range ending within existing
        with self.assertRaises(ValidationError):
            iprange_4_198_201 = IPRange.objects.create(
                start_address=IPNetwork('1.2.4.198/24'), end_address=IPNetwork('1.2.4.201/24')
            )
            iprange_4_198_201.clean()


class TestPrefix(TestCase):

    def test_get_duplicates(self):
        prefixes = Prefix.objects.bulk_create((
            Prefix(prefix=IPNetwork('192.0.2.0/24')),
            Prefix(prefix=IPNetwork('192.0.2.0/24')),
            Prefix(prefix=IPNetwork('192.0.2.0/24')),
        ))
        duplicate_prefix_pks = [p.pk for p in prefixes[0].get_duplicates()]

        self.assertSetEqual(set(duplicate_prefix_pks), {prefixes[1].pk, prefixes[2].pk})

    def test_get_child_prefixes(self):
        vrfs = VRF.objects.bulk_create((
            VRF(name='VRF 1'),
            VRF(name='VRF 2'),
            VRF(name='VRF 3'),
        ))
        prefixes = Prefix.objects.bulk_create((
            Prefix(prefix=IPNetwork('10.0.0.0/16'), status=PrefixStatusChoices.STATUS_CONTAINER),
            Prefix(prefix=IPNetwork('10.0.0.0/24'), vrf=None),
            Prefix(prefix=IPNetwork('10.0.1.0/24'), vrf=vrfs[0]),
            Prefix(prefix=IPNetwork('10.0.2.0/24'), vrf=vrfs[1]),
            Prefix(prefix=IPNetwork('10.0.3.0/24'), vrf=vrfs[2]),
        ))
        child_prefix_pks = {p.pk for p in prefixes[0].get_child_prefixes()}

        # Global container should return all children
        self.assertSetEqual(child_prefix_pks, {prefixes[1].pk, prefixes[2].pk, prefixes[3].pk, prefixes[4].pk})

        prefixes[0].vrf = vrfs[0]
        prefixes[0].save()
        child_prefix_pks = {p.pk for p in prefixes[0].get_child_prefixes()}

        # VRF container is limited to its own VRF
        self.assertSetEqual(child_prefix_pks, {prefixes[2].pk})

    def test_get_child_ranges(self):
        prefix = Prefix(prefix='192.168.0.16/28')
        prefix.save()
        ranges = IPRange.objects.bulk_create(
            (
                # No overlap
                IPRange(
                    start_address=IPNetwork('192.168.0.1/24'), end_address=IPNetwork('192.168.0.10/24'), size=10
                ),
                # Partial overlap
                IPRange(
                    start_address=IPNetwork('192.168.0.11/24'), end_address=IPNetwork('192.168.0.17/24'), size=7
                ),
                # Full overlap
                IPRange(
                    start_address=IPNetwork('192.168.0.18/24'), end_address=IPNetwork('192.168.0.23/24'), size=6
                ),
                # Full overlap
                IPRange(
                    start_address=IPNetwork('192.168.0.24/24'), end_address=IPNetwork('192.168.0.30/24'), size=7
                ),
                # Partial overlap
                IPRange(
                    start_address=IPNetwork('192.168.0.31/24'), end_address=IPNetwork('192.168.0.40/24'), size=10
                ),
            )
        )

        child_ranges = prefix.get_child_ranges()

        self.assertEqual(len(child_ranges), 2)
        self.assertEqual(child_ranges[0], ranges[2])
        self.assertEqual(child_ranges[1], ranges[3])

    def test_get_child_ips(self):
        vrfs = VRF.objects.bulk_create((
            VRF(name='VRF 1'),
            VRF(name='VRF 2'),
            VRF(name='VRF 3'),
        ))
        parent_prefix = Prefix.objects.create(
            prefix=IPNetwork('10.0.0.0/16'), status=PrefixStatusChoices.STATUS_CONTAINER
        )
        ips = IPAddress.objects.bulk_create((
            IPAddress(address=IPNetwork('10.0.0.1/24'), vrf=None),
            IPAddress(address=IPNetwork('10.0.1.1/24'), vrf=vrfs[0]),
            IPAddress(address=IPNetwork('10.0.2.1/24'), vrf=vrfs[1]),
            IPAddress(address=IPNetwork('10.0.3.1/24'), vrf=vrfs[2]),
        ))
        child_ip_pks = {p.pk for p in parent_prefix.get_child_ips()}

        # Global container should return all children
        self.assertSetEqual(child_ip_pks, {ips[0].pk, ips[1].pk, ips[2].pk, ips[3].pk})

        parent_prefix.vrf = vrfs[0]
        parent_prefix.save()
        child_ip_pks = {p.pk for p in parent_prefix.get_child_ips()}

        # VRF container is limited to its own VRF
        self.assertSetEqual(child_ip_pks, {ips[1].pk})

    def test_get_available_prefixes(self):

        prefixes = Prefix.objects.bulk_create((
            Prefix(prefix=IPNetwork('10.0.0.0/16')),  # Parent prefix
            Prefix(prefix=IPNetwork('10.0.0.0/20')),
            Prefix(prefix=IPNetwork('10.0.32.0/20')),
            Prefix(prefix=IPNetwork('10.0.128.0/18')),
        ))
        missing_prefixes = IPSet([
            IPNetwork('10.0.16.0/20'),
            IPNetwork('10.0.48.0/20'),
            IPNetwork('10.0.64.0/18'),
            IPNetwork('10.0.192.0/18'),
        ])
        available_prefixes = prefixes[0].get_available_prefixes()

        self.assertEqual(available_prefixes, missing_prefixes)

    def test_get_available_ips(self):

        parent_prefix = Prefix.objects.create(prefix=IPNetwork('10.0.0.0/28'))
        IPAddress.objects.bulk_create((
            IPAddress(address=IPNetwork('10.0.0.1/26')),
            IPAddress(address=IPNetwork('10.0.0.3/26')),
            IPAddress(address=IPNetwork('10.0.0.5/26')),
            IPAddress(address=IPNetwork('10.0.0.7/26')),
        ))
        IPRange.objects.create(
            start_address=IPNetwork('10.0.0.9/26'),
            end_address=IPNetwork('10.0.0.12/26')
        )
        missing_ips = IPSet([
            '10.0.0.2/32',
            '10.0.0.4/32',
            '10.0.0.6/32',
            '10.0.0.8/32',
            '10.0.0.13/32',
            '10.0.0.14/32',
        ])
        available_ips = parent_prefix.get_available_ips()

        self.assertEqual(available_ips, missing_ips)

    def test_get_first_available_prefix(self):

        prefixes = Prefix.objects.bulk_create((
            Prefix(prefix=IPNetwork('10.0.0.0/16')),  # Parent prefix
            Prefix(prefix=IPNetwork('10.0.0.0/24')),
            Prefix(prefix=IPNetwork('10.0.1.0/24')),
            Prefix(prefix=IPNetwork('10.0.2.0/24')),
        ))
        self.assertEqual(prefixes[0].get_first_available_prefix(), IPNetwork('10.0.3.0/24'))

        Prefix.objects.create(prefix=IPNetwork('10.0.3.0/24'))
        self.assertEqual(prefixes[0].get_first_available_prefix(), IPNetwork('10.0.4.0/22'))

    def test_get_first_available_ip(self):

        parent_prefix = Prefix.objects.create(prefix=IPNetwork('10.0.0.0/24'))
        IPAddress.objects.bulk_create((
            IPAddress(address=IPNetwork('10.0.0.1/24')),
            IPAddress(address=IPNetwork('10.0.0.2/24')),
            IPAddress(address=IPNetwork('10.0.0.3/24')),
        ))
        self.assertEqual(parent_prefix.get_first_available_ip(), '10.0.0.4/24')

        IPAddress.objects.create(address=IPNetwork('10.0.0.4/24'))
        self.assertEqual(parent_prefix.get_first_available_ip(), '10.0.0.5/24')

    def test_get_first_available_ip_ipv6(self):
        parent_prefix = Prefix.objects.create(prefix=IPNetwork('2001:db8:500::/64'))
        self.assertEqual(parent_prefix.get_first_available_ip(), '2001:db8:500::1/64')

    def test_get_first_available_ip_ipv6_rfc3627(self):
        parent_prefix = Prefix.objects.create(prefix=IPNetwork('2001:db8:500:4::/126'))
        self.assertEqual(parent_prefix.get_first_available_ip(), '2001:db8:500:4::1/126')

    def test_get_first_available_ip_ipv6_rfc6164(self):
        parent_prefix = Prefix.objects.create(prefix=IPNetwork('2001:db8:500:5::/127'))
        self.assertEqual(parent_prefix.get_first_available_ip(), '2001:db8:500:5::/127')

    def test_get_utilization_container(self):
        prefixes = (
            Prefix(prefix=IPNetwork('10.0.0.0/24'), status=PrefixStatusChoices.STATUS_CONTAINER),
            Prefix(prefix=IPNetwork('10.0.0.0/26')),
            Prefix(prefix=IPNetwork('10.0.0.128/26')),
        )
        Prefix.objects.bulk_create(prefixes)
        self.assertEqual(prefixes[0].get_utilization(), 50)  # 50% utilization

    def test_get_utilization_noncontainer(self):
        prefix = Prefix.objects.create(
            prefix=IPNetwork('10.0.0.0/24'),
            status=PrefixStatusChoices.STATUS_ACTIVE
        )

        # Create 32 child IPs
        IPAddress.objects.bulk_create([
            IPAddress(address=IPNetwork(f'10.0.0.{i}/24')) for i in range(1, 33)
        ])
        self.assertEqual(prefix.get_utilization(), 32 / 254 * 100)  # ~12.5% utilization

        # Create a child range with 32 additional IPs
        IPRange.objects.create(start_address=IPNetwork('10.0.0.33/24'), end_address=IPNetwork('10.0.0.64/24'))
        self.assertEqual(prefix.get_utilization(), 64 / 254 * 100)  # ~25% utilization

    #
    # Uniqueness enforcement tests
    #

    @override_settings(ENFORCE_GLOBAL_UNIQUE=False)
    def test_duplicate_global(self):
        Prefix.objects.create(prefix=IPNetwork('192.0.2.0/24'))
        duplicate_prefix = Prefix(prefix=IPNetwork('192.0.2.0/24'))
        self.assertIsNone(duplicate_prefix.clean())

    def test_duplicate_global_unique(self):
        Prefix.objects.create(prefix=IPNetwork('192.0.2.0/24'))
        duplicate_prefix = Prefix(prefix=IPNetwork('192.0.2.0/24'))
        self.assertRaises(ValidationError, duplicate_prefix.clean)

    def test_duplicate_vrf(self):
        vrf = VRF.objects.create(name='Test', rd='1:1', enforce_unique=False)
        Prefix.objects.create(vrf=vrf, prefix=IPNetwork('192.0.2.0/24'))
        duplicate_prefix = Prefix(vrf=vrf, prefix=IPNetwork('192.0.2.0/24'))
        self.assertIsNone(duplicate_prefix.clean())

    def test_duplicate_vrf_unique(self):
        vrf = VRF.objects.create(name='Test', rd='1:1', enforce_unique=True)
        Prefix.objects.create(vrf=vrf, prefix=IPNetwork('192.0.2.0/24'))
        duplicate_prefix = Prefix(vrf=vrf, prefix=IPNetwork('192.0.2.0/24'))
        self.assertRaises(ValidationError, duplicate_prefix.clean)


class TestPrefixHierarchy(TestCase):
    """
    Test the automatic updating of depth and child count in response to changes made within
    the prefix hierarchy.
    """
    @classmethod
    def setUpTestData(cls):

        prefixes = (

            # IPv4
            Prefix(prefix='10.0.0.0/8', _depth=0, _children=2),
            Prefix(prefix='10.0.0.0/16', _depth=1, _children=1),
            Prefix(prefix='10.0.0.0/24', _depth=2, _children=0),

            # IPv6
            Prefix(prefix='2001:db8::/32', _depth=0, _children=2),
            Prefix(prefix='2001:db8::/40', _depth=1, _children=1),
            Prefix(prefix='2001:db8::/48', _depth=2, _children=0),

        )
        Prefix.objects.bulk_create(prefixes)

    def test_create_prefix4(self):
        # Create 10.0.0.0/12
        Prefix(prefix='10.0.0.0/12').save()

        prefixes = Prefix.objects.filter(prefix__family=4)
        self.assertEqual(prefixes[0].prefix, IPNetwork('10.0.0.0/8'))
        self.assertEqual(prefixes[0]._depth, 0)
        self.assertEqual(prefixes[0]._children, 3)
        self.assertEqual(prefixes[1].prefix, IPNetwork('10.0.0.0/12'))
        self.assertEqual(prefixes[1]._depth, 1)
        self.assertEqual(prefixes[1]._children, 2)
        self.assertEqual(prefixes[2].prefix, IPNetwork('10.0.0.0/16'))
        self.assertEqual(prefixes[2]._depth, 2)
        self.assertEqual(prefixes[2]._children, 1)
        self.assertEqual(prefixes[3].prefix, IPNetwork('10.0.0.0/24'))
        self.assertEqual(prefixes[3]._depth, 3)
        self.assertEqual(prefixes[3]._children, 0)

    def test_create_prefix6(self):
        # Create 2001:db8::/36
        Prefix(prefix='2001:db8::/36').save()

        prefixes = Prefix.objects.filter(prefix__family=6)
        self.assertEqual(prefixes[0].prefix, IPNetwork('2001:db8::/32'))
        self.assertEqual(prefixes[0]._depth, 0)
        self.assertEqual(prefixes[0]._children, 3)
        self.assertEqual(prefixes[1].prefix, IPNetwork('2001:db8::/36'))
        self.assertEqual(prefixes[1]._depth, 1)
        self.assertEqual(prefixes[1]._children, 2)
        self.assertEqual(prefixes[2].prefix, IPNetwork('2001:db8::/40'))
        self.assertEqual(prefixes[2]._depth, 2)
        self.assertEqual(prefixes[2]._children, 1)
        self.assertEqual(prefixes[3].prefix, IPNetwork('2001:db8::/48'))
        self.assertEqual(prefixes[3]._depth, 3)
        self.assertEqual(prefixes[3]._children, 0)

    def test_update_prefix4(self):
        # Change 10.0.0.0/24 to 10.0.0.0/12
        p = Prefix.objects.get(prefix='10.0.0.0/24')
        p.prefix = '10.0.0.0/12'
        p.save()

        prefixes = Prefix.objects.filter(prefix__family=4)
        self.assertEqual(prefixes[0].prefix, IPNetwork('10.0.0.0/8'))
        self.assertEqual(prefixes[0]._depth, 0)
        self.assertEqual(prefixes[0]._children, 2)
        self.assertEqual(prefixes[1].prefix, IPNetwork('10.0.0.0/12'))
        self.assertEqual(prefixes[1]._depth, 1)
        self.assertEqual(prefixes[1]._children, 1)
        self.assertEqual(prefixes[2].prefix, IPNetwork('10.0.0.0/16'))
        self.assertEqual(prefixes[2]._depth, 2)
        self.assertEqual(prefixes[2]._children, 0)

    def test_update_prefix6(self):
        # Change 2001:db8::/48 to 2001:db8::/36
        p = Prefix.objects.get(prefix='2001:db8::/48')
        p.prefix = '2001:db8::/36'
        p.save()

        prefixes = Prefix.objects.filter(prefix__family=6)
        self.assertEqual(prefixes[0].prefix, IPNetwork('2001:db8::/32'))
        self.assertEqual(prefixes[0]._depth, 0)
        self.assertEqual(prefixes[0]._children, 2)
        self.assertEqual(prefixes[1].prefix, IPNetwork('2001:db8::/36'))
        self.assertEqual(prefixes[1]._depth, 1)
        self.assertEqual(prefixes[1]._children, 1)
        self.assertEqual(prefixes[2].prefix, IPNetwork('2001:db8::/40'))
        self.assertEqual(prefixes[2]._depth, 2)
        self.assertEqual(prefixes[2]._children, 0)

    def test_update_prefix_vrf4(self):
        vrf = VRF(name='VRF A')
        vrf.save()

        # Move 10.0.0.0/16 to a VRF
        p = Prefix.objects.get(prefix='10.0.0.0/16')
        p.vrf = vrf
        p.save()

        prefixes = Prefix.objects.filter(vrf__isnull=True, prefix__family=4)
        self.assertEqual(prefixes[0].prefix, IPNetwork('10.0.0.0/8'))
        self.assertEqual(prefixes[0]._depth, 0)
        self.assertEqual(prefixes[0]._children, 1)
        self.assertEqual(prefixes[1].prefix, IPNetwork('10.0.0.0/24'))
        self.assertEqual(prefixes[1]._depth, 1)
        self.assertEqual(prefixes[1]._children, 0)

        prefixes = Prefix.objects.filter(vrf=vrf)
        self.assertEqual(prefixes[0].prefix, IPNetwork('10.0.0.0/16'))
        self.assertEqual(prefixes[0]._depth, 0)
        self.assertEqual(prefixes[0]._children, 0)

    def test_update_prefix_vrf6(self):
        vrf = VRF(name='VRF A')
        vrf.save()

        # Move 2001:db8::/40 to a VRF
        p = Prefix.objects.get(prefix='2001:db8::/40')
        p.vrf = vrf
        p.save()

        prefixes = Prefix.objects.filter(vrf__isnull=True, prefix__family=6)
        self.assertEqual(prefixes[0].prefix, IPNetwork('2001:db8::/32'))
        self.assertEqual(prefixes[0]._depth, 0)
        self.assertEqual(prefixes[0]._children, 1)
        self.assertEqual(prefixes[1].prefix, IPNetwork('2001:db8::/48'))
        self.assertEqual(prefixes[1]._depth, 1)
        self.assertEqual(prefixes[1]._children, 0)

        prefixes = Prefix.objects.filter(vrf=vrf)
        self.assertEqual(prefixes[0].prefix, IPNetwork('2001:db8::/40'))
        self.assertEqual(prefixes[0]._depth, 0)
        self.assertEqual(prefixes[0]._children, 0)

    def test_delete_prefix4(self):
        # Delete 10.0.0.0/16
        Prefix.objects.filter(prefix='10.0.0.0/16').delete()

        prefixes = Prefix.objects.filter(prefix__family=4)
        self.assertEqual(prefixes[0].prefix, IPNetwork('10.0.0.0/8'))
        self.assertEqual(prefixes[0]._depth, 0)
        self.assertEqual(prefixes[0]._children, 1)
        self.assertEqual(prefixes[1].prefix, IPNetwork('10.0.0.0/24'))
        self.assertEqual(prefixes[1]._depth, 1)
        self.assertEqual(prefixes[1]._children, 0)

    def test_delete_prefix6(self):
        # Delete 2001:db8::/40
        Prefix.objects.filter(prefix='2001:db8::/40').delete()

        prefixes = Prefix.objects.filter(prefix__family=6)
        self.assertEqual(prefixes[0].prefix, IPNetwork('2001:db8::/32'))
        self.assertEqual(prefixes[0]._depth, 0)
        self.assertEqual(prefixes[0]._children, 1)
        self.assertEqual(prefixes[1].prefix, IPNetwork('2001:db8::/48'))
        self.assertEqual(prefixes[1]._depth, 1)
        self.assertEqual(prefixes[1]._children, 0)

    def test_duplicate_prefix4(self):
        # Duplicate 10.0.0.0/16
        Prefix(prefix='10.0.0.0/16').save()

        prefixes = Prefix.objects.filter(prefix__family=4)
        self.assertEqual(prefixes[0].prefix, IPNetwork('10.0.0.0/8'))
        self.assertEqual(prefixes[0]._depth, 0)
        self.assertEqual(prefixes[0]._children, 3)
        self.assertEqual(prefixes[1].prefix, IPNetwork('10.0.0.0/16'))
        self.assertEqual(prefixes[1]._depth, 1)
        self.assertEqual(prefixes[1]._children, 1)
        self.assertEqual(prefixes[2].prefix, IPNetwork('10.0.0.0/16'))
        self.assertEqual(prefixes[2]._depth, 1)
        self.assertEqual(prefixes[2]._children, 1)
        self.assertEqual(prefixes[3].prefix, IPNetwork('10.0.0.0/24'))
        self.assertEqual(prefixes[3]._depth, 2)
        self.assertEqual(prefixes[3]._children, 0)

    def test_duplicate_prefix6(self):
        # Duplicate 2001:db8::/40
        Prefix(prefix='2001:db8::/40').save()

        prefixes = Prefix.objects.filter(prefix__family=6)
        self.assertEqual(prefixes[0].prefix, IPNetwork('2001:db8::/32'))
        self.assertEqual(prefixes[0]._depth, 0)
        self.assertEqual(prefixes[0]._children, 3)
        self.assertEqual(prefixes[1].prefix, IPNetwork('2001:db8::/40'))
        self.assertEqual(prefixes[1]._depth, 1)
        self.assertEqual(prefixes[1]._children, 1)
        self.assertEqual(prefixes[2].prefix, IPNetwork('2001:db8::/40'))
        self.assertEqual(prefixes[2]._depth, 1)
        self.assertEqual(prefixes[2]._children, 1)
        self.assertEqual(prefixes[3].prefix, IPNetwork('2001:db8::/48'))
        self.assertEqual(prefixes[3]._depth, 2)
        self.assertEqual(prefixes[3]._children, 0)


class TestIPAddress(TestCase):

    def test_get_duplicates(self):
        ips = IPAddress.objects.bulk_create((
            IPAddress(address=IPNetwork('192.0.2.1/24')),
            IPAddress(address=IPNetwork('192.0.2.1/24')),
            IPAddress(address=IPNetwork('192.0.2.1/24')),
        ))
        duplicate_ip_pks = [p.pk for p in ips[0].get_duplicates()]

        self.assertSetEqual(set(duplicate_ip_pks), {ips[1].pk, ips[2].pk})

    #
    # Uniqueness enforcement tests
    #

    @override_settings(ENFORCE_GLOBAL_UNIQUE=False)
    def test_duplicate_global(self):
        IPAddress.objects.create(address=IPNetwork('192.0.2.1/24'))
        duplicate_ip = IPAddress(address=IPNetwork('192.0.2.1/24'))
        self.assertIsNone(duplicate_ip.clean())

    def test_duplicate_global_unique(self):
        IPAddress.objects.create(address=IPNetwork('192.0.2.1/24'))
        duplicate_ip = IPAddress(address=IPNetwork('192.0.2.1/24'))
        self.assertRaises(ValidationError, duplicate_ip.clean)

    def test_duplicate_vrf(self):
        vrf = VRF.objects.create(name='Test', rd='1:1', enforce_unique=False)
        IPAddress.objects.create(vrf=vrf, address=IPNetwork('192.0.2.1/24'))
        duplicate_ip = IPAddress(vrf=vrf, address=IPNetwork('192.0.2.1/24'))
        self.assertIsNone(duplicate_ip.clean())

    def test_duplicate_vrf_unique(self):
        vrf = VRF.objects.create(name='Test', rd='1:1', enforce_unique=True)
        IPAddress.objects.create(vrf=vrf, address=IPNetwork('192.0.2.1/24'))
        duplicate_ip = IPAddress(vrf=vrf, address=IPNetwork('192.0.2.1/24'))
        self.assertRaises(ValidationError, duplicate_ip.clean)

    def test_duplicate_nonunique_nonrole_role(self):
        IPAddress.objects.create(address=IPNetwork('192.0.2.1/24'))
        duplicate_ip = IPAddress(address=IPNetwork('192.0.2.1/24'), role=IPAddressRoleChoices.ROLE_VIP)
        self.assertRaises(ValidationError, duplicate_ip.clean)

    def test_duplicate_nonunique_role_nonrole(self):
        IPAddress.objects.create(address=IPNetwork('192.0.2.1/24'), role=IPAddressRoleChoices.ROLE_VIP)
        duplicate_ip = IPAddress(address=IPNetwork('192.0.2.1/24'))
        self.assertRaises(ValidationError, duplicate_ip.clean)

    def test_duplicate_nonunique_role(self):
        IPAddress.objects.create(address=IPNetwork('192.0.2.1/24'), role=IPAddressRoleChoices.ROLE_VIP)
        IPAddress.objects.create(address=IPNetwork('192.0.2.1/24'), role=IPAddressRoleChoices.ROLE_VIP)


class TestVLANGroup(TestCase):

    @classmethod
    def setUpTestData(cls):
        vlangroup = VLANGroup.objects.create(
            name='VLAN Group 1',
            slug='vlan-group-1',
            vid_ranges=string_to_ranges('100-199'),
        )
        VLAN.objects.bulk_create((
            VLAN(name='VLAN 100', vid=100, group=vlangroup),
            VLAN(name='VLAN 101', vid=101, group=vlangroup),
            VLAN(name='VLAN 102', vid=102, group=vlangroup),
            VLAN(name='VLAN 103', vid=103, group=vlangroup),
        ))

    def test_get_available_vids(self):
        vlangroup = VLANGroup.objects.first()
        child_vids = VLAN.objects.filter(group=vlangroup).values_list('vid', flat=True)
        self.assertEqual(len(child_vids), 4)

        available_vids = vlangroup.get_available_vids()
        self.assertListEqual(available_vids, list(range(104, 200)))

    def test_get_next_available_vid(self):
        vlangroup = VLANGroup.objects.first()
        self.assertEqual(vlangroup.get_next_available_vid(), 104)

        VLAN.objects.create(name='VLAN 104', vid=104, group=vlangroup)
        self.assertEqual(vlangroup.get_next_available_vid(), 105)

    def test_vid_validation(self):
        vlangroup = VLANGroup.objects.first()

        vlan = VLAN(vid=1, name='VLAN 1', group=vlangroup)
        with self.assertRaises(ValidationError):
            vlan.full_clean()

        vlan = VLAN(vid=109, name='VLAN 109', group=vlangroup)
        vlan.full_clean()

    def test_overlapping_vlan(self):
        vlangroup = VLANGroup(
            name='VLAN Group 1',
            slug='vlan-group-1',
            vid_ranges=string_to_ranges('2-4,3-5'),
        )
        with self.assertRaises(ValidationError):
            vlangroup.full_clean()

        # make sure single vlan range works
        vlangroup.vid_ranges = string_to_ranges('2-2')
        vlangroup.full_clean()
        vlangroup.save()


class TestVLAN(TestCase):

    @classmethod
    def setUpTestData(cls):
        VLAN.objects.bulk_create((
            VLAN(name='VLAN 1', vid=1, qinq_role=VLANQinQRoleChoices.ROLE_SERVICE),
        ))

    def test_qinq_role(self):
        svlan = VLAN.objects.filter(qinq_role=VLANQinQRoleChoices.ROLE_SERVICE).first()

        vlan = VLAN(
            name='VLAN X',
            vid=999,
            qinq_role=VLANQinQRoleChoices.ROLE_SERVICE,
            qinq_svlan=svlan
        )
        with self.assertRaises(ValidationError):
            vlan.full_clean()

    def test_vlan_group_site_validation(self):
        sitegroup = SiteGroup.objects.create(
            name='Site Group 1',
            slug='site-group-1',
        )
        sites = Site.objects.bulk_create((
            Site(
                name='Site 1',
                slug='site-1',
            ),
            Site(
                name='Site 2',
                slug='site-2',
            ),
        ))
        sitegroup.sites.add(sites[0])
        vlangroups = VLANGroup.objects.bulk_create((
            VLANGroup(
                name='VLAN Group 1',
                slug='vlan-group-1',
                scope=sitegroup,
                scope_type=ContentType.objects.get_for_model(SiteGroup),
            ),
            VLANGroup(
                name='VLAN Group 2',
                slug='vlan-group-2',
                scope=sites[0],
                scope_type=ContentType.objects.get_for_model(Site),
            ),
            VLANGroup(
                name='VLAN Group 2',
                slug='vlan-group-2',
                scope=sites[1],
                scope_type=ContentType.objects.get_for_model(Site),
            ),
        ))
        vlan = VLAN(
            name='VLAN 1',
            vid=1,
            group=vlangroups[0],
            site=sites[0],
        )

        # VLAN Group 1 and 2 should be valid
        vlan.full_clean()
        vlan.group = vlangroups[1]
        vlan.full_clean()
        vlan.group = vlangroups[2]
        with self.assertRaises(ValidationError):
            vlan.full_clean()
