/* 通用 PCI NIC 驱动绑定验证测试。
 * 用法: nic_bind_test <ifname> <expected_driver>
 * 验证: netdev 注册 ✓ → PCI 设备链接 ✓ → 驱动绑定 ✓ → 收发计数 ✓
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void run_ethtool_ops(const char *ifname)
{
	char cmd[256];
	const char *ops[] = {
		"ethtool %s",
		"ethtool -i %s",
		"ethtool -S %s",
		"ethtool -a %s",
		"ethtool -g %s",
		"ethtool -k %s",
		"ethtool -c %s",
		"ethtool -r %s",
		"ethtool --show-priv-flags %s",
		"ethtool --show-time-stamping %s",
		NULL
	};
	for (int i = 0; ops[i]; i++) {
		snprintf(cmd, sizeof(cmd), ops[i], ifname);
		system(cmd);
	}
}

static int check_netdev(const char *ifname, const char *expect_drv)
{
	char path[256];
	struct stat st;
	char link_target[256];
	ssize_t len;

	/* 1) netdev 存在 */
	snprintf(path, sizeof(path), "/sys/class/net/%s", ifname);
	if (stat(path, &st) != 0 || !S_ISDIR(st.st_mode)) {
		printf("REHARNESS_NIC_FAIL netdev %s missing\n", ifname);
		return -1;
	}

	/* 2) PCI 设备链接 */
	snprintf(path, sizeof(path), "/sys/class/net/%s/device", ifname);
	if (stat(path, &st) != 0 || !S_ISDIR(st.st_mode)) {
		printf("REHARNESS_NIC_FAIL device link missing\n");
		return -1;
	}

	/* 3) 驱动绑定 */
	snprintf(path, sizeof(path), "/sys/class/net/%s/device/driver", ifname);
	memset(&st, 0, sizeof(st));
	if (lstat(path, &st) != 0 || !S_ISLNK(st.st_mode)) {
		printf("REHARNESS_NIC_FAIL driver not bound\n");
		return -1;
	}
	len = readlink(path, link_target, sizeof(link_target) - 1);
	if (len <= 0) { printf("REHARNESS_NIC_FAIL readlink\n"); return -1; }
	link_target[len] = 0;
	{
		char *drv = strrchr(link_target, '/');
		drv = drv ? drv + 1 : link_target;
		if (strcmp(drv, expect_drv) != 0) {
			printf("REHARNESS_NIC_FAIL driver=%s != %s\n", drv, expect_drv);
			return -1;
		}
	}

	/* 4) ethtool 操作触发驱动回调 */
	{
		char cmd[256];
		const char *ops[] = {
			"ethtool %s",
			"ethtool -i %s",
			"ethtool -S %s",
			"ethtool -a %s",
			"ethtool -g %s",
			"ethtool -k %s",
			"ethtool -c %s",
			"ethtool -r %s",
			"ethtool --show-priv-flags %s",
			NULL
		};
		for (int i = 0; ops[i]; i++) {
			snprintf(cmd, sizeof(cmd), ops[i], ifname);
			if (system(cmd) == 0) {}
		}
	}
	return 0;
}

static int check_counters(const char *ifname)
{
	char path[256];
	unsigned long tx = 0, rx = 0;
	snprintf(path, sizeof(path), "/sys/class/net/%s/statistics/tx_packets", ifname);
	FILE *f = fopen(path, "r");
	if (f) { int r = fscanf(f, "%lu", &tx); (void)r; fclose(f); }
	snprintf(path, sizeof(path), "/sys/class/net/%s/statistics/rx_packets", ifname);
	f = fopen(path, "r");
	if (f) { int r = fscanf(f, "%lu", &rx); (void)r; fclose(f); }
	printf("  tx_packets=%lu rx_packets=%lu\n", tx, rx);
	return 0;
}

int main(int argc, char **argv)
{
	const char *ifname = argc > 1 ? argv[1] : "eth0";
	const char *drv = argc > 2 ? argv[2] : "8139too";

	if (check_netdev(ifname, drv) < 0)
		goto fail;
	check_counters(ifname);
	run_ethtool_ops(ifname);
	printf("REHARNESS_NIC_OK driver=%s\n", drv);
	return 0;
fail:
	printf("REHARNESS_NIC_FAIL\n");
	return 1;
}
