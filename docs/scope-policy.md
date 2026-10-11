# Scope policy

These rules apply to every model.

| Area | Policy |
| --- | --- |
| Firmware and over-the-air update services | Never written, not even for research. Reading firmware identity is fine. Writing to an unknown characteristic that may belong to an update path is excluded too. |
| Writes to device settings | Only once the exact format is known from a capture or the vendor app, and with the owner's consent for the first test. Clock writes are the only candidates today. |
| Cloud and vendor accounts | None. Everything stays on the local Bluetooth link. |
| Unverified models | A profile may only claim support after a test on the real device. Code written from guesses is not shipped. |
| Captures in the repository | Allowed in documents and tests, with serial numbers and Bluetooth addresses masked. Pairing keys never. |
