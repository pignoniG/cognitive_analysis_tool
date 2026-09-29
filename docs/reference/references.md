# References

## This tool

The methods implemented here:

- Pignoni, G., Komandur, S., & Volden, F. (2021). Accounting for effects of variation in luminance in pupillometry
  for field measurements of cognitive workload. *IEEE Sensors Journal*.
  [doi:10.1109/JSEN.2020.3038291](https://doi.org/10.1109/JSEN.2020.3038291). The lux sensor method (eq. 5–8) used
  for the glasses (Pupil Core, Neon, Glasses 3).
- Pignoni, G., Grandi, F., & Peruzzini, M. *Toward Reliable Pupillometry in Extended Reality Environments: A
  Video-Based Pipeline for Isolating Cognitive Workload from Pupil Data*. **Manuscript in preparation, not yet
  published**; the method may change before publication. Display photometric calibration, two-area luminance and the
  calibration sequence used for the Varjo XR-4. Pages that refer to "the Varjo manuscript" mean this text.

Related publications using the tool and its lux sensor:

- Pignoni, G., & Komandur, S. (2019). Development of a quantitative evaluation tool of cognitive workload in field
  studies through eye tracking. *Lecture Notes in Computer Science*, 11571.
  [doi:10.1007/978-3-030-22507-0_9](https://doi.org/10.1007/978-3-030-22507-0_9)
- Pignoni, G., Hareide, O. S., Komandur, S., & Volden, F. (2019). Trial application of pupillometry for a maritime
  usability study in field conditions. *Necesse*, 4.
  [NTNU Open](https://ntnuopen.ntnu.no/ntnu-xmlui/handle/11250/2633600)
- Streilein, T., Komandur, S., Pignoni, G., Volden, F., Lunde, P., & Mjelde, F. V. (2020). Maritime navigation:
  characterizing collaboration in a high-speed craft navigation activity. *Communications in Computer and Information
  Science*, 1224. [PDF](https://fhs.brage.unit.no/fhs-xmlui/bitstream/handle/11250/2786638/HCI_International_2020_Tim-3.pdf?sequence=1&isAllowed=y)
- Pignoni, G., & Komandur, S. (2022). Practical challenges in using eye trackers in the field. In *Human-Automation
  Interaction: Mobile Computing* (pp. 653–662). Springer.
  [doi:10.1007/978-3-031-10788-7_37](https://doi.org/10.1007/978-3-031-10788-7_37)

## Models

- Watson, A. B., & Yellott, J. I. (2012). A unified formula for light-adapted pupil size. *Journal of Vision*,
  12(10):12.
- Stanley, P. A., & Davies, A. K. (1995). The effect of field of view size on steady-state pupil diameter.
  *Ophthalmic & Physiological Optics*, 15(6), 601–603.

## Related work

- Eckert, M., Robotham, T., Habets, E. A. P., & Rummukainen, O. S. (2022). Pupillary light reflex correction for
  robust pupillometry in virtual reality. *Proc. ACM Comput. Graph. Interact. Tech.*, 5(2), Article 18.
  [doi:10.1145/3530798](https://doi.org/10.1145/3530798). Per-participant mapping functions from calibration
  sequences (6 s steps in pseudo-random order proved most robust) and luminance from a weighted average of the
  fixation area and the background.

## Data formats

- Varjo Base eye tracking recorder output (checked against an April 2026 export).
- Pupil Labs, Pupil Core raw data exporter (Pupil Player).
- Pupil Labs, [Neon recording format](https://docs.pupil-labs.com/neon/data-collection/data-format/) and
  [pl-neon-recording](https://github.com/pupil-labs/pl-neon-recording).
