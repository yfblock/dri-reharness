#include <linux/module.h>
#include <linux/usb.h>

static int delay_use_set(const char *val, const struct kernel_param *kp)
{
	return 0;
}

static int delay_use_get(char *buffer, const struct kernel_param *kp)
{
	return 0;
}

static int storage_probe(struct usb_interface *intf,
			 const struct usb_device_id *id)
{
	return 0;
}

static void usb_stor_disconnect(struct usb_interface *intf)
{
}

static int usb_stor_suspend(struct usb_interface *intf, pm_message_t message)
{
	return 0;
}

static int usb_stor_resume(struct usb_interface *intf)
{
	return 0;
}

static int usb_stor_reset_resume(struct usb_interface *intf)
{
	return 0;
}

static int usb_stor_pre_reset(struct usb_interface *intf)
{
	return 0;
}

static int usb_stor_post_reset(struct usb_interface *intf)
{
	return 0;
}

static const struct usb_device_id usb_storage_ids[] = {
	{ }
};
MODULE_DEVICE_TABLE(usb, usb_storage_ids);

static struct usb_driver usb_storage_driver = {
	.name = "usb-storage",
	.probe = storage_probe,
	.disconnect = usb_stor_disconnect,
	.suspend = usb_stor_suspend,
	.resume = usb_stor_resume,
	.reset_resume = usb_stor_reset_resume,
	.pre_reset = usb_stor_pre_reset,
	.post_reset = usb_stor_post_reset,
	.id_table = usb_storage_ids,
};

module_usb_driver(usb_storage_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("USB storage driver harness");
