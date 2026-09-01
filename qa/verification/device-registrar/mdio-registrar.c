// SPDX-License-Identifier: GPL-2.0
/* Deterministic MDIO bus and device fixture for generic profile tests. */
#include <linux/mdio.h>
#include <linux/mii.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/phy.h>
#include <linux/uaccess.h>

#define REHARNESS_MDIO_ADDRESS 1
#define REHARNESS_MDIO_REGISTER 0x10
#define REHARNESS_MDIO_READ _IOWR('R', 0x40, struct reharness_mdio_request)
#define REHARNESS_MDIO_WRITE _IOW('R', 0x41, struct reharness_mdio_request)

struct reharness_mdio_request {
	u8 address;
	u8 reg;
	u16 value;
};

static struct mii_bus *reharness_mdio_bus;
static struct mdio_device *reharness_mdio_device;
static DEFINE_MUTEX(reharness_mdio_lock);
static u16 reharness_mdio_registers[PHY_MAX_ADDR][32];
static char *device_name = "reharness_mdio_sensor";
module_param(device_name, charp, 0444);
MODULE_PARM_DESC(device_name, "MDIO device name matched by the driver");

static int reharness_mdio_read(struct mii_bus *bus, int address, int reg)
{
	int value;

	if (address != REHARNESS_MDIO_ADDRESS || reg < 0 || reg >= 32)
		return -ENODEV;

	mutex_lock(&reharness_mdio_lock);
	value = reharness_mdio_registers[address][reg];
	mutex_unlock(&reharness_mdio_lock);
	return value;
}

static int reharness_mdio_write(struct mii_bus *bus, int address, int reg,
				u16 value)
{
	if (address != REHARNESS_MDIO_ADDRESS || reg < 0 || reg >= 32)
		return -ENODEV;

	mutex_lock(&reharness_mdio_lock);
	reharness_mdio_registers[address][reg] = value;
	mutex_unlock(&reharness_mdio_lock);
	return 0;
}

static int reharness_mdio_match(struct device *dev,
				const struct device_driver *driver)
{
	return driver->name && device_name &&
		!strcmp(driver->name, device_name);
}

static long reharness_mdio_control_ioctl(struct file *file,
					 unsigned int command, unsigned long argument)
{
	struct reharness_mdio_request request;
	int value;

	if (command != REHARNESS_MDIO_READ && command != REHARNESS_MDIO_WRITE)
		return -ENOTTY;
	if (copy_from_user(&request, (void __user *)argument, sizeof(request)))
		return -EFAULT;

	if (command == REHARNESS_MDIO_READ) {
		value = mdiobus_read(reharness_mdio_bus, request.address,
					     request.reg);
		if (value < 0)
			return value;
		request.value = value;
		if (copy_to_user((void __user *)argument, &request,
					 sizeof(request)))
			return -EFAULT;
		return 0;
	}

	return mdiobus_write(reharness_mdio_bus, request.address,
				     request.reg, request.value);
}

static const struct file_operations reharness_mdio_control_fops = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = reharness_mdio_control_ioctl,
};

static struct miscdevice reharness_mdio_control_device = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "reharness-mdio-control",
	.fops = &reharness_mdio_control_fops,
	.mode = 0666,
};

static int __init reharness_mdio_registrar_init(void)
{
	int ret;

	if (!device_name || !*device_name)
		return -EINVAL;

	ret = misc_register(&reharness_mdio_control_device);
	if (ret)
		return ret;

	reharness_mdio_bus = mdiobus_alloc();
	if (!reharness_mdio_bus) {
		ret = -ENOMEM;
		goto unregister_misc;
	}
	reharness_mdio_bus->owner = THIS_MODULE;
	reharness_mdio_bus->parent = reharness_mdio_control_device.this_device;
	reharness_mdio_bus->name = "reharness-mdio-bus";
	strscpy(reharness_mdio_bus->id, "reharness-mdio-bus",
			sizeof(reharness_mdio_bus->id));
	reharness_mdio_bus->read = reharness_mdio_read;
	reharness_mdio_bus->write = reharness_mdio_write;
	/* Prevent the generic PHY scan; this fixture owns one non-PHY device. */
	reharness_mdio_bus->phy_mask = GENMASK(PHY_MAX_ADDR - 1, 0);
	reharness_mdio_registers[REHARNESS_MDIO_ADDRESS]
		[REHARNESS_MDIO_REGISTER] = 0x5a5a;

	ret = mdiobus_register(reharness_mdio_bus);
	if (ret)
		goto free_bus;

	reharness_mdio_device = mdio_device_create(reharness_mdio_bus,
						 REHARNESS_MDIO_ADDRESS);
	if (IS_ERR(reharness_mdio_device)) {
		ret = PTR_ERR(reharness_mdio_device);
		reharness_mdio_device = NULL;
		goto unregister_bus;
	}
	reharness_mdio_device->bus_match = reharness_mdio_match;
	ret = mdio_device_register(reharness_mdio_device);
	if (ret)
		goto free_device;

	pr_info("REHARNESS_MDIO_DEVICE_READY address=%d\n",
		REHARNESS_MDIO_ADDRESS);
	return 0;

free_device:
	mdio_device_free(reharness_mdio_device);
	reharness_mdio_device = NULL;
unregister_bus:
	mdiobus_unregister(reharness_mdio_bus);
free_bus:
	mdiobus_free(reharness_mdio_bus);
	reharness_mdio_bus = NULL;
unregister_misc:
	misc_deregister(&reharness_mdio_control_device);
	return ret;
}

static void __exit reharness_mdio_registrar_exit(void)
{
	if (reharness_mdio_device) {
		mdio_device_remove(reharness_mdio_device);
		mdio_device_free(reharness_mdio_device);
		reharness_mdio_device = NULL;
	}
	if (reharness_mdio_bus) {
		mdiobus_unregister(reharness_mdio_bus);
		mdiobus_free(reharness_mdio_bus);
		reharness_mdio_bus = NULL;
	}
	misc_deregister(&reharness_mdio_control_device);
	pr_info("REHARNESS_MDIO_REGISTRAR_UNLOADED\n");
}

module_init(reharness_mdio_registrar_init);
module_exit(reharness_mdio_registrar_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Deterministic MDIO bus and device fixture");
