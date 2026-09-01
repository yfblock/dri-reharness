// SPDX-License-Identifier: GPL-2.0-only
/* A bus-neutral net_device fixture for the generic network profile. */
#include <linux/etherdevice.h>
#include <linux/module.h>
#include <linux/netdevice.h>

static struct net_device *reharness_netdev;

static int reharness_network_open(struct net_device *dev)
{
	netif_carrier_on(dev);
	netif_start_queue(dev);
	pr_info("REHARNESS_NETWORK_OPEN name=%s\n", dev->name);
	return 0;
}

static int reharness_network_stop(struct net_device *dev)
{
	netif_stop_queue(dev);
	netif_carrier_off(dev);
	return 0;
}

static netdev_tx_t reharness_network_xmit(struct sk_buff *skb,
						struct net_device *dev)
{
	dev->stats.tx_packets++;
	dev->stats.tx_bytes += skb->len;
	dev_kfree_skb(skb);
	return NETDEV_TX_OK;
}

static const struct net_device_ops reharness_network_ops = {
	.ndo_open = reharness_network_open,
	.ndo_stop = reharness_network_stop,
	.ndo_start_xmit = reharness_network_xmit,
	.ndo_set_mac_address = eth_mac_addr,
};

static int __init reharness_network_init(void)
{
	int ret;

	reharness_netdev = alloc_netdev(0, "eth%d", NET_NAME_UNKNOWN,
					ether_setup);
	if (!reharness_netdev)
		return -ENOMEM;

	reharness_netdev->netdev_ops = &reharness_network_ops;
	reharness_netdev->min_mtu = ETH_MIN_MTU;
	reharness_netdev->max_mtu = ETH_DATA_LEN;
	eth_hw_addr_random(reharness_netdev);
	ret = register_netdev(reharness_netdev);
	if (ret) {
		free_netdev(reharness_netdev);
		reharness_netdev = NULL;
		return ret;
	}
	pr_info("REHARNESS_NETWORK_REGISTERED name=%s\n", reharness_netdev->name);
	return 0;
}

static void __exit reharness_network_exit(void)
{
	if (!reharness_netdev)
		return;
	unregister_netdev(reharness_netdev);
	free_netdev(reharness_netdev);
	reharness_netdev = NULL;
}

module_init(reharness_network_init);
module_exit(reharness_network_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("reharness generic network device fixture");
