obj-m += ftgpio010_gpio.o
KERNELDIR ?= /home/yfblock/Code/linux
all:
	$(MAKE) -C $(KERNELDIR) M=$(PWD) modules
clean:
	$(MAKE) -C $(KERNELDIR) M=$(PWD) clean
.PHONY: all clean
