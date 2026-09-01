/* Freestanding PID-1 for multi-arch QEMU experiments.
 * 裸系统调用实现，无 libc 依赖：x86_64 / arm64 / riscv64 原生编译。
 *
 * 用法: /init <module.ko> [more.ko...] --expect <substring>
 * 流程: 挂载伪文件系统 → 依序 insmod → 轮询内核日志等待期望子串 →
 *       打印 REHARNESS_EXPECT_FOUND=0|1 → 完整内核日志尾部 → 关机。
 */
typedef unsigned long u64;
typedef long s64;

#if defined(__aarch64__)
static inline long syscall6(long n, long a, long b, long c, long d, long e, long f) {
    register long x8 __asm__("x8") = n;
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    register long x3 __asm__("x3") = d;
    register long x4 __asm__("x4") = e;
    register long x5 __asm__("x5") = f;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5) : "memory", "cc");
    return x0;
}
#elif defined(__riscv) && __riscv_xlen == 64
static inline long syscall6(long n, long a, long b, long c, long d, long e, long f) {
    register long a7 __asm__("a7") = n;
    register long a0 __asm__("a0") = a;
    register long a1 __asm__("a1") = b;
    register long a2 __asm__("a2") = c;
    register long a3 __asm__("a3") = d;
    register long a4 __asm__("a4") = e;
    register long a5 __asm__("a5") = f;
    __asm__ volatile("ecall" : "+r"(a0) : "r"(a7), "r"(a0), "r"(a1), "r"(a2), "r"(a3), "r"(a4), "r"(a5) : "memory");
    return a0;
}
#elif defined(__x86_64__)
static inline long syscall6(long n, long a, long b, long c, long d, long e, long f) {
    long ret;
    __asm__ volatile("syscall" : "=a"(ret) : "a"(n), "D"(a), "S"(b), "d"(c), "r"(d), "r"(e), "r"(f) : "rcx", "r11", "memory");
    return ret;
}
#else
#error "unsupported architecture"
#endif

/* x86_64 使用历史系统调用表;arm64/riscv64 使用 asm-generic 表 */
#if defined(__x86_64__)
#define SYS_MOUNT 165
#define SYS_OPENAT 257
#define SYS_CLOSE 3
#define SYS_WRITE 1
#define SYS_CLOCK_NANOSLEEP 230
#define SYS_SYSLOG 103
#define SYS_REBOOT 169
#define SYS_FINIT_MODULE 313
#define SYS_EXIT_GROUP 231
#else /* asm-generic: arm64 / riscv64 */
#define SYS_MOUNT 40
#define SYS_OPENAT 56
#define SYS_CLOSE 57
#define SYS_WRITE 64
#define SYS_CLOCK_NANOSLEEP 115
#define SYS_SYSLOG 116
#define SYS_REBOOT 142
#define SYS_FINIT_MODULE 273
#define SYS_EXIT_GROUP 94
#endif
#define AT_FDCWD (-100)
#define O_RDONLY 0
#define CLOCK_MONOTONIC 1
#define SYSLOG_ACTION_READ_ALL 3
#define RB_POWER_OFF 0x4321fed9

static long sys_write(long fd, const char *s, u64 len) {
    return syscall6(SYS_WRITE, fd, (long)s, len, 0, 0, 0);
}
static u64 slen(const char *s) { u64 n = 0; while (s[n]) n++; return n; }
static void puts_(const char *s) { sys_write(1, s, slen(s)); }
static void putsn(const char *s) { puts_(s); puts_("\n"); }
static void putu(long v) {
    char b[24]; int i = 23; b[i--] = 0;
    if (v == 0) b[i--] = '0';
    while (v > 0) { b[i--] = '0' + (v % 10); v /= 10; }
    sys_write(1, &b[i + 1], 23 - (i + 1));
}
static void sleep_100ms(void) {
    struct { s64 sec; s64 nsec; } req = {0, 100 * 1000 * 1000};
    syscall6(SYS_CLOCK_NANOSLEEP, CLOCK_MONOTONIC, 0, (long)&req, 0, 0, 0);
}
static int streq(const char *a, const char *b) {
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}
static int contains(const char *hay, u64 hlen, const char *needle) {
    u64 n = slen(needle);
    if (n == 0 || hlen < n) return 0;
    for (u64 i = 0; i + n <= hlen; i++) {
        u64 j = 0;
        while (j < n && hay[i + j] == needle[j]) j++;
        if (j == n) return 1;
    }
    return 0;
}

static char klog[1 << 17];
static u64 klog_read(void) {
    return (u64)syscall6(SYS_SYSLOG, SYSLOG_ACTION_READ_ALL, (long)klog, sizeof(klog) - 1, 0, 0, 0);
}

void _start(void) {
    /* argv 由内核传入栈顶;此处直接解析 /proc? 无需——用编译期常量更简单:
     * 模块路径与期望子串通过 -D 注入。 */
    extern char MODULE_KO[];
    extern char EXPECT[];
    extern char MODULE_BASE[];

    puts_("BOOT\n");
    syscall6(SYS_MOUNT, (long)"proc", (long)"/proc", (long)"proc", 0, 0, 0);
    puts_("MOUNTED\n");
    syscall6(SYS_MOUNT, (long)"sysfs", (long)"/sys", (long)"sysfs", 0, 0, 0);
    syscall6(SYS_MOUNT, (long)"devtmpfs", (long)"/dev", (long)"devtmpfs", 0, 0, 0);

    /* finit_module(/dev/<name>.ko 之外的路径): openat + finit_module */
    long fd = syscall6(SYS_OPENAT, AT_FDCWD, (long)MODULE_KO, O_RDONLY, 0, 0, 0);
    puts_("REHARNESS_MODULE_OPEN ");
    putu((long)fd);
    puts_("\n");
    if (fd >= 0) {
        long rc = syscall6(SYS_FINIT_MODULE, fd, (long)MODULE_KO, 0, 0, 0, 0);
        puts_("REHARNESS_MODULE_LOAD rc=");
        putu(rc);
        puts_("\n");
        syscall6(SYS_CLOSE, fd, 0, 0, 0, 0, 0);
    } else {
        puts_("REHARNESS_MODULE_LOAD rc=open-failed\n");
    }

    int found = 0;
    for (int attempt = 0; attempt < 100 && !found; attempt++) {
        u64 n = klog_read();
        if (n > sizeof(klog) - 1) n = sizeof(klog) - 1;
        klog[n] = 0;
        if (contains(klog, n, EXPECT)) found = 1;
        sleep_100ms();
    }
    puts_("REHARNESS_EXPECT_FOUND=");
    putu(found);
    puts_("\nREHARNESS_EXPECT_PATTERN=");
    putsn(EXPECT);
    u64 n = klog_read();
    if (n > sizeof(klog) - 1) n = sizeof(klog) - 1;
    sys_write(1, klog, n);

    syscall6(SYS_REBOOT, 0xfee1dead, 672274793, RB_POWER_OFF, 0, 0, 0);
    syscall6(SYS_EXIT_GROUP, 0, 0, 0, 0, 0, 0);
    for (;;) {}
}

char MODULE_KO[] = "/edu.ko";
char EXPECT[] = "[rhcov] edu_probe";
char MODULE_BASE[] = "edu";
