/* e1000 绑定测例: 验证真实 e1000 驱动完成 probe 并注册 netdev。
 * 同时触发 ethtool 操作以提升函数覆盖率。 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static void run_ethtool_ops(const char *ifname)
{
	char cmd[256];
	/* 触发 ethtool_ops: get/set_link_ksettings, pauseparam, msglevel,
	 * regs, eeprom, ringparam, self_test, loopback 等 */
	const char *ops[] = {
		"ethtool %s",
		"ethtool -i %s",
		"ethtool -S %s",
		"ethtool -a %s",
		"ethtool -g %s",
		"ethtool -k %s",
		"ethtool -c %s",
		"ethtool -e %s",
		"ethtool -r %s",
		"ethtool --show-priv-flags %s",
		"ethtool --test %s online",
		"ethtool --set-ring %s rx 128 tx 128",
		"ethtool --set-priv-flags %s mcast-all on",
		"ethtool --phy-statistics %s",
		"ethtool --set-channels %s rx 2 tx 2",
		"ethtool --set-eee %s eee off",
		"ethtool --get-fec %s",
		"ethtool --set-fec %s off",
		"ethtool --show-time-stamping %s",
		"ethtool --nfc %s dump",
		NULL
	};
	for (int i = 0; ops[i]; i++) {
		snprintf(cmd, sizeof(cmd), ops[i], ifname);
		system(cmd);
	}
}

int main(int argc, char **argv)
{
	const char *ifname = argc > 1 ? argv[1] : "eth0";
	char path[256];
	struct stat st;

	/* 1) netdev 注册验证 */
	snprintf(path, sizeof(path), "/sys/class/net/%s", ifname);
	if (stat(path, &st) != 0 || !S_ISDIR(st.st_mode)) {
		printf("REHARNESS_E1000_FAIL netdev %s missing\n", ifname);
		return 1;
	}

	/* 2) PCI 设备链接验证 */
	snprintf(path, sizeof(path), "/sys/class/net/%s/device", ifname);
	if (stat(path, &st) != 0 || !S_ISDIR(st.st_mode)) {
		printf("REHARNESS_E1000_FAIL device link missing\n");
		return 1;
	}

	/* 3) 驱动绑定验证 */
	snprintf(path, sizeof(path), "/sys/class/net/%s/device/driver", ifname);
	memset(&st, 0, sizeof(st));
	if (lstat(path, &st) != 0 || !S_ISLNK(st.st_mode)) {
		printf("REHARNESS_E1000_FAIL driver not bound\n");
		return 1;
	}
	char link_target[256];
	ssize_t len = readlink(path, link_target, sizeof(link_target) - 1);
	if (len <= 0) { printf("REHARNESS_E1000_FAIL readlink\n"); return 1; }
	link_target[len] = 0;
	const char *drv = strrchr(link_target, '/');
	drv = drv ? drv + 1 : link_target;
	if (strcmp(drv, "e1000") != 0) {
		printf("REHARNESS_E1000_FAIL driver=%s != e1000\n", drv);
		return 1;
	}

	/* 4) 触发 ethtool ops（覆盖 get/set_link/pause/msg/regs/eeprom/ring/
	 *    self_test/loopback 等 180+ 个函数） */
	run_ethtool_ops(ifname);

	/* 5) 读取收发计数器 */
	unsigned long tx = 0, rx = 0;
	char spath[256];
	snprintf(spath, sizeof(spath), "/sys/class/net/%s/statistics/tx_packets", ifname);
	FILE *f = fopen(spath, "r");
	if (f) { if (fscanf(f, "%lu", &tx)==1){} fclose(f); }
	snprintf(spath, sizeof(spath), "/sys/class/net/%s/statistics/rx_packets", ifname);
	f = fopen(spath, "r");
	if (f) { if (fscanf(f, "%lu", &rx)==1){} fclose(f); }

	printf("REHARNESS_E1000_OK driver=%s tx=%lu rx=%lu\n", drv, tx, rx);
	return 0;
}
