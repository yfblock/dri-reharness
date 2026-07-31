obj-m += device-registrar.o

KERNELDIR ?= /usr/src/linux-headers-$(shell uname -r)

all:
	$(MAKE) -C $(KERNELDIR) M=$(CURDIR) modules

clean:
	$(MAKE) -C $(KERNELDIR) M=$(CURDIR) clean

.PHONY: all clean
