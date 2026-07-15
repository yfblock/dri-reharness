obj-m += ftgpio010_gpio.o
KERNELDIR ?= ../../linux
all:
	$(MAKE) -C $(KERNELDIR) M=$(CURDIR) modules
clean:
	$(MAKE) -C $(KERNELDIR) M=$(CURDIR) clean
.PHONY: all clean
