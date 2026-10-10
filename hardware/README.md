# Hardware

The carrier PCB that turns the toy into a Rave & Repeat table. The full build, with
photos, is on the [project website](https://nastypieceof.work/raveandrepeat).

| File | What it is |
| --- | --- |
| `DJTable-gerbers.zip` | Ready to upload to a PCB maker (JLCPCB, PCBWay and others): copper, mask, silkscreen, outline and drill files. 2 layers. |
| `DJTable-schematic.pdf` | The schematic, for reading without KiCad. |
| `kicad/` | The KiCad 10 project (schematic, PCB and its own footprint library), if you want to change the board. Open `DJTable.kicad_pro`. |

## Read before you build

This is the board revision that was built and works, with these fixes made by hand.
**The PCB files don't include them yet.**

1. **Wire the amp's SD pin to Raspberry Pi header pin 7** (GPIO4). That's pin 7 of the
   Pi's 40-pin header, not of the amp module. The software uses it to mute the amp while
   it loads a new theme. Without it, theme changes crackle.
2. **Wire the amp's GAIN pin to ground.** This sets the amp to 12 dB, louder than the
   9 dB it gives with GAIN left unconnected.
3. **The Raspberry Pi mounts upside-down**, with its chips facing the carrier board. Oops
4. **The toy's original switches don't fit this board**, although that was the plan.
   Use these instead. Both fit the board and work with the toy:
   - **SS-23D03-G4** three-position slide switches for Level and Volume (SW4, SW5);
   - **PS-12F03-G5** push switches for the three Tone buttons (SW1–SW3). The G4 also
     works, but its shorter plunger needs the board lined up exactly before screwing it in.
5. **Bridge R2** with a 0 Ω resistor or a wire. It connects the Mode button; it was left
   as an option on this board and isn't needed as a resistor.

## Parts

| Qty | Ref | Part | Notes |
| ---: | --- | --- | --- |
| 1 | U1 | Raspberry Pi Zero 2 W | With a 2×20 male header |
| 1 | U1 | 2×20 female socket, 2.54 mm | |
| 1 | U2 | INMP441 microphone module | |
| 1 | U3 | MAX98357A amplifier module (Adafruit-style) | Plus the SD and GAIN wires above |
| 3 | SW1–SW3 | PS-12F03-G5 push switch | Tone |
| 2 | SW4–SW5 | SS-23D03-G4 slide switch, 3-position | Level and Volume |
| 2 | SW6–SW7 | 6×6 mm tactile switch, through-hole | Record and Mode |
| 1 | R1 | 330 Ω, 1206 | Song button LED |
| 1 | R2 | 0 Ω, 1206, or a wire | **Bridge it**: connects the Mode button |
| 2 | R6–R7 | 33 Ω, 1206 | I2S clock lines |
| 3 | C2, C3, C4 | 100 nF ceramic, 1206, 16 V+ | |
| 1 | C1 | 220 µF 10 V electrolytic | |
| 1 | C5 | 47 µF 10 V electrolytic | |
| 1 | F1 | Resettable fuse, 2 A hold, 6 V+, 1812 | |
| — | J1–J6 | 2.54 mm pin headers, or solder the wires in | See connectors below |

Off the board:
- an AS5600 magnetic angle module with a diametric magnet, for the platter;
- USB C connector.
- 3D printed parts (below).

Power the table only through J3, never through the Pi's USB port at the same time.

## 3D printed parts

STL files in [`3d-prints/`](3d-prints/).

| Part | What it does | Needed? |
| --- | --- | --- |
| `Platter Mount.STL` | Replaces the toy's platter mount, with a pocket to glue in the AS5600's magnet | Yes |
| `AS5600 Mount.STL` | Holds the AS5600 under the platter; takes a 5 mm LED too if you want one. Replaces the toy's button and LED board | Yes |
| `Mode Button.STL` | A working Mode button. On Learn & Play tables without language changing, that button is only a dummy | Only for those tables |
| `Speaker Holder.STL` | Lets you fit a more powerful speaker in place of the original | Optional |

## Connectors

| Connector | Pins |
| --- | --- |
| J1 Keyboard | 1 GND, 2 pink, 3 red, 4 orange, 5 green, 6 yellow, 7 blue, 8 purple, 9 black |
| J2 Song button | 1 switch GND, 2 switch, 3 LED −, 4 LED + |
| J3 Power in | 1 +5 V, 2 GND |
| J4, J5 | Spare 5 V outputs (1 +5 V, 2 GND) |
| J6 AS5600 | 1 VCC (3.3 V), 2 OUT (unused), 3 GND, 4 DIR (GND), 5 SCL, 6 SDA, 7 GPO (unused) |

## Raspberry Pi pins

All buttons and switches connect a pin to ground; the software turns on the pull-ups.

| Control | GPIO (BCM) | Header pin |
| --- | --- | --- |
| Keys pink, red, orange, green | 5, 6, 12, 13 | 29, 31, 32, 33 |
| Keys yellow, blue, purple, black | 16, 17, 22, 27 | 36, 11, 15, 13 |
| Tone 1 / 2 / 3 | 7 / 24 / 23 | 26 / 18 / 16 |
| Level 1 / 2 / 3 | 8 / 26 / 25 | 24 / 37 / 22 |
| Volume low / medium / high | 15 / 14 / 9 | 10 / 8 / 21 |
| Song | 10 | 19 |
| Record | 11 | 23 |
| Mode | 0 | 27 |
| Amp mute (amp SD) | 4 | 7 |
| I2S bit clock / frame clock | 18 / 19 | 12 / 35 |
| Mic data / speaker data | 20 / 21 | 38 / 40 |
| AS5600 SDA / SCL | 2 / 3 | 3 / 5 |
