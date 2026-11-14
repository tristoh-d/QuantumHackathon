# Generic Data for Hackathon (TVA)

*A text copy of the Word document TVA shared on Nov 2, 2026. The wording and links are TVA's.*

## Best overall choice

### 1. RTS-GMLC Reliability Test System

[Download the RTS-GMLC repository](https://github.com/GridMod/RTS-GMLC)

This is the best starting point for example economic dispatch and unit-commitment calculations because the same system is supplied in:

- Open-source CSV files
- MATPOWER
- PLEXOS
- Prescient
- PowerWorld
- PSS/E
- pandapower
- PowerSystems.jl and other formats

The underlying source tables include thermal and renewable generators, buses, branches, generator limits, ramp rates, heat-rate curves, fuel prices, startup costs, minimum up/down times, reserves, load, and renewable time series. It was specifically developed to support production-cost modeling. ([github.com](https://github.com/GridMod/RTS-GMLC), [prescient.readthedocs.io](https://prescient.readthedocs.io/en/stable/reference/file_formats/rts-gmlc/gen.html))

**Relevant directories**

- `RTS_Data/SourceData`: master CSV tables
- `RTS_Data/timeseries_data_files`: load, wind, solar, hydro and related time-series inputs
- `RTS_Data/FormattedData/MATPOWER`: MATPOWER case
- `RTS_Data/FormattedData/PLEXOS`: PLEXOS-formatted model
- `RTS_Data/FormattedData/Prescient`: detailed unit-commitment input

**The generator CSV specification includes:**

- Fuel and unit type
- Minimum and maximum MW
- Ramp rates
- Heat-rate curve points
- Fuel price
- Startup cost
- Minimum up/down time
- Cold-start parameters
- Thermal and renewable generator identification ([prescient.readthedocs.io](https://prescient.readthedocs.io/en/stable/reference/file_formats/rts-gmlc/gen.html))

**Important MATPOWER note:** the supplied MATPOWER case is primarily a peak-load power-flow/OPF representation, and renewable generation is disabled by default in that snapshot. For chronological dispatch, combine the MATPOWER network case with the RTS-GMLC source CSV and time-series files, or use the included PLEXOS/Prescient model. ([github.com](https://github.com/GridMod/RTS-GMLC/blob/master/RTS_Data/FormattedData/MATPOWER/README.md))

**Recommended use:** Start here for a transparent 24-hour, week-long, or annual dispatch example with thermal commitment, renewables, reserves, and storage.
