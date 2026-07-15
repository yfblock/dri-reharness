#include <linux/regmap.h>

void regmap_access(struct regmap *map, unsigned int reg)
{
	u32 value;
	u32 values[2];

	regmap_read(map, reg, &value);
	regmap_write(map, reg + 4, value);
	regmap_update_bits(map, reg + 8, 0xff, 0x55);
	regmap_bulk_read(map, reg + 12, values, 2);
}
