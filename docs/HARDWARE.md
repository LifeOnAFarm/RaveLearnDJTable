# GPIO connections

BCM numbers below are GPIO numbers, not header positions. All switches close
to GND; software enables internal pull-ups. No external 10k array is required.
Disconnect power before wiring. Use 3.3 V signals, never 5 V on GPIO.

| Control | BCM | Physical header pin |
| --- | --- | --- |
| Pink / Circle | 5 | 29 |
| Red / Heart | 6 | 31 |
| Orange / Triangle | 12 | 32 |
| Green / Square | 13 | 33 |
| Yellow / Star | 16 | 36 |
| Blue / Hexagon | 17 | 11 |
| Purple / Moon | 22 | 15 |
| Black / Diamond | 27 | 13 |
| Tone 1 / 2 / 3 | 7 / 24 / 23 | 26 / 18 / 16 |
| Level English / Irish / notes | 8 / 26 / 25 | 24 / 37 / 22 |
| Volume low / medium / high | 15 / 14 / 9 | 10 / 8 / 21 |
| Random song | 10 | 19 |
| Record | 11 | 23 |

Tone can use three momentary buttons: releasing all retains the last selection.
Level/volume selectors ground exactly one input per position; invalid combinations
retain the previous setting. Switch pad numbering depends on the actual part.

## Audio: MAX98357A speaker and INMP441 microphone

Both chips share the Pi's I2S clocks. One overlay (`deploy/djtable-duplex-overlay.dts`)
drives both; never add a second sound overlay.

| Signal | Pi BCM / pin | MAX98357A | INMP441 |
| --- | --- | --- | --- |
| Bit clock | BCM18 / 12 | BCLK | SCK |
| Frame clock | BCM19 / 35 | LRC | WS |
| Speaker data (Pi → amp) | BCM21 / 40 | DIN | — |
| Mic data (mic → Pi) | BCM20 / 38 | — | SD |
| Amp mute | BCM4 / 7 | SD (SD_MODE) | — |
| Power | — | VIN → 5 V | VDD → 3.3 V (never 5 V) |
| Ground | GND | GND | GND and L/R |

- **Wire amp SD to BCM4 (pin 7).** The driver holds it high while audio runs and
  low when the stream stops; DJTable stops the stream during theme changes so
  the amp is silent while samples load from the SD card. Without this wire the
  module's onboard pull-up keeps the amp always on and theme changes can crackle.
  With BCM4 driving SD high the amp plays the left channel; DJTable sends the same
  mono mix to both channels.
- **Mic SD (pin 38) and amp DIN (pin 40) are neighbours.** A bridge or a shared net
  feeds microphone data straight into the amplifier: constant noise and acoustic
  feedback even with capture disabled. Meter both before first power-up.
- **L/R to GND** puts the mic in the left slot (`mic_channel: 0`). The right
  channel then reads exact zero, which is expected.
- BCLK/LRC: keep the 33 Ω series resistors at the Pi end, route as one line per
  clock (Pi → mic → amp, no long branches) and away from the speaker outputs.
- Decoupling: 100 nF ceramic at each chip's supply pin, plus bulk (47 µF or more)
  at the amp's VIN. A small RC (10 Ω + 1 µF) from the Pi's 3.3 V keeps amplifier
  current pulses off the mic supply.
- Speaker connects only between SPK+ and SPK−. Module headers are not numbered
  consistently across vendors. GAIN unconnected gives 9 dB.

## Platter

AS5600: VCC → 3.3 V; GND and DIR → GND; SCL → BCM3/pin5;
SDA → BCM2/pin3; OUT and GPO unused. Verify the module supports 3.3 V operation.

## Mode button

Momentary button from **BCM0 / physical pin 27** to GND. The software enables the pull-up.

- **Tap** (acts on release): next Learning theme (Teenage Disco → House → Punk →
  Baby Raver → …), exactly like the webpage; the amp mutes for the 2–3 s load.
  Ignored in Music Maker and Bluetooth.
- **Hold 5 seconds**: next keyboard mode (Learning → Music Maker → Bluetooth → …),
  announced while you are still holding.

Both are ignored while recording or processing.

BCM0 is the HAT ID EEPROM data line (ID_SD). That is fine as long as no HAT
EEPROM is fitted and `dtparam=i2c_vc=on` is not set. Do not press it while the
Pi is booting; the firmware briefly probes this pin.

A possible CS4344 MCLK has not been implemented.

## Power

Carrier power input supplies the Pi through its 5 V header. Do not also connect
USB power when using that carrier supply. Use a regulated supply (3 A or more),
shared ground, and the carrier's fuse. Use a 5 V track of 1 mm or wider; a
resettable fuse should hold 2.5–3 A. Shutdown the OS before opening the external
power switch. `vcgencmd get_throttled` should report `0x0`.

This source release does not include or certify a PCB layout. Verify the pin
map against your assembled board before enabling GPIO mode.
