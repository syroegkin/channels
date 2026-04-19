
#include <stdint.h>
typedef uint8_t uchar;

#define tiles gui_tiles_data
#include "tiles.h"
#undef tiles

uint8_t* get_gui_tiles()
{
    return gui_tiles_data;
}
