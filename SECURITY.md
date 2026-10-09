# Security

DJTable is a toy for a trusted home network. Its web pages have **no accounts or
passwords**: anyone on the same network can change modes, upload songs and join the
table to another Wi-Fi network. Do not forward a router port to it, and do not run it
on a public or shared network.

The Wi-Fi fallback hotspot (`deploy/install-hotspot.sh`) uses a WPA2 password you
choose; pick a long one. Bluetooth pairing is accepted only during the two-minute
window after Bluetooth mode is chosen on the table.

## Reporting a problem

Please report security problems privately, using GitHub's **Security → Report a
vulnerability** on this repository, rather than in a public issue. Include the release
or commit, what you did and what happened. Do not include your Wi-Fi names, passwords,
IP addresses or recordings.
