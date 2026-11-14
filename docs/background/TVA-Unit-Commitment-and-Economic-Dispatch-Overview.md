# Utility Generation Unit Commitment and Economic Dispatch

*A high-level overview of generation types, operating characteristics, cost inputs, and decision logic*

*A text copy of the Word document TVA shared on Nov 2, 2026, as background for this track. The wording is TVA's.*

> **Executive summary**
>
> Unit commitment determines which generating resources should be online. Economic dispatch determines how much each committed resource should produce. Together, they minimize total operating cost while meeting load, reserve, transmission, environmental, and equipment constraints.

## 1. The Operating Problem

Utilities and grid operators must continuously balance electricity supply and demand. Because electricity generally must be produced when it is consumed, operators forecast conditions, commit resources in advance, and then adjust output as actual conditions change.

- Meet forecast and actual customer demand
- Maintain operating reserves for contingencies and forecast error
- Respect generator, fuel, environmental, and transmission limits
- Accommodate variable renewable production
- Minimize total system operating cost, not merely the cost of the next megawatt

## 2. Two Related Decisions

| Process | Primary question | Typical timing | Main cost focus |
|---|---|---|---|
| Unit Commitment | Which generating units should be online? | Day-ahead, hours-ahead, and multi-day | Startup, shutdown, no-load, fuel, and minimum-run implications |
| Economic Dispatch | How much should each online unit generate? | Hourly to 5-minute intervals, with faster control layers | Incremental or marginal production cost subject to system constraints |

### Unit Commitment

Unit commitment is a discrete on/off scheduling problem. It is necessary because many thermal units require substantial time and cost to start, cannot operate below a minimum output, and must remain online or offline for minimum periods.

### Economic Dispatch

Economic dispatch allocates load among the committed units. In the simplest view, available generation is loaded from lowest to highest marginal cost. In practice, ramp rates, reserves, transmission congestion, security constraints, and other operating limits can change the order.

## 3. Key Planning Inputs

| Input | Why it matters |
|---|---|
| Load forecast | Defines expected energy demand by interval and the shape of the daily peak. |
| Wind and solar forecasts | Reduce net load but add uncertainty and ramping needs. |
| Fuel prices and availability | Drive variable cost and may restrict output or commitment. |
| Unit availability | Accounts for planned maintenance, forced outages, derates, and testing. |
| Reserve requirements | Ensures capacity is available for generator trips, load error, and renewable forecast error. |
| Transmission topology and limits | May prevent the lowest-cost generator from serving a constrained location. |
| Hydro conditions and storage state | Determine water value, reservoir constraints, and future flexibility. |
| Environmental and regulatory limits | Constrain emissions, run hours, water use, or fuel consumption. |

## 4. Generation Types, Characteristics, and Typical Roles

| Resource | Operating characteristics | Typical system role | Cost profile |
|---|---|---|---|
| Nuclear | Large units; very slow startup and ramping; high minimum output; long operating cycles | Baseload energy and stable output | Low fuel and marginal cost; high fixed and outage costs; very high restart implications |
| Coal steam | Slow startup; limited ramping; minimum load and minimum up/down times | Baseload or intermediate duty where economic | Moderate fuel cost; high startup cost; variable heat rate; emissions and consumables |
| Gas combined cycle | Efficient; moderate startup; good ramping; multiple configurations possible | Intermediate and load-following energy | Fuel-price sensitive; moderate startup and variable O&M; generally lower heat rate than peakers |
| Combustion turbine / peaker | Fast start; fast ramp; lower efficiency; flexible minimum run | Peak demand, contingency reserves, and rapid response | High marginal fuel cost; relatively low startup cost and short commitment lead time |
| Hydroelectric | Fast response; flexible output; energy limited by water | Peaking, regulation, reserves, and energy shifting | Low direct operating cost; opportunity cost based on water value and reservoir needs |
| Wind | Weather-dependent; near-zero short-run marginal cost; may be curtailed | Energy supply when available | No fuel cost; production tax credits or contracts may influence bid behavior |
| Solar | Daylight-dependent; near-zero short-run marginal cost; strong daily profile | Daytime energy supply | No fuel cost; curtailment and integration costs may matter operationally |
| Battery storage | Very fast response; charge/discharge limits; finite duration; efficiency losses | Regulation, reserves, peak shifting, congestion relief | Charging cost, round-trip losses, degradation, and opportunity value of stored energy |
| Demand response | Reduces or shifts load rather than generating | Peak reduction, reserves, and emergency response | Program payment, customer interruption cost, and activation limits |

## 5. Cost Components Used in Evaluation

| Cost component | Typical treatment |
|---|---|
| Fuel cost | Heat rate multiplied by fuel price. Often the largest variable cost for thermal units. |
| Variable operations and maintenance | Consumables, wear-related maintenance, water treatment, and other output-driven expenses, usually expressed in $/MWh. |
| Startup cost | Fuel, auxiliary power, staffing, and equipment wear required to bring a unit online. May vary for hot, warm, or cold starts. |
| No-load cost | Cost to keep a synchronized unit online before accounting for incremental energy output. |
| Shutdown cost | Explicit shutdown expense or modeled cycling impact, where applicable. |
| Emissions cost | Allowance or compliance cost for CO2, NOx, SO2, and other regulated emissions. |
| Opportunity cost | Value of conserving limited water, stored energy, fuel, emissions allowances, or run hours for later periods. |
| Reliability and constraint penalties | Costs assigned to reserve shortages, unserved energy, constraint violations, or emergency actions. |
| Long-term cycling and maintenance impact | Starts, ramps, and low-load operation can accelerate wear; some planning models include these effects. |

> **Simplified thermal marginal cost**
>
> Marginal cost (dollars/MWh) = Heat rate (fuel units/MWh) × Fuel price (dollars/fuel unit) + Variable O&M + Emissions cost. Startup and no-load costs are especially important in unit commitment because they affect whether it is economical to turn a unit on or keep it running.

## 6. Operational and Reliability Constraints

- Minimum and maximum output: each unit has a feasible operating range.
- Ramp rate: output can increase or decrease only so quickly.
- Minimum up and down times: a unit may have to remain online after startup or remain offline after shutdown.
- Startup lead time and condition: hot, warm, and cold starts have different durations and costs.
- Reserve capability: some capacity must remain unloaded and capable of responding.
- Transmission limits: line ratings, contingencies, voltage needs, and congestion may require local generation.
- Fuel, water, environmental, and permit limits: these can cap output or operating hours.
- Security criteria: the dispatch must remain reliable following credible equipment outages.

## 7. How the Decision Is Made

| Step | What happens |
|---|---|
| 1. Forecast | Estimate load, renewable output, outages, fuel conditions, and transfer capability. |
| 2. Build requirements | Establish energy demand, reserve needs, and reliability constraints for each interval. |
| 3. Optimize commitment | Select the on/off schedule that minimizes total multi-period cost while preserving feasibility. |
| 4. Dispatch committed units | Allocate output based on incremental cost and operational constraints. |
| 5. Validate security | Test transmission and contingency performance; redispatch or commit additional resources if needed. |
| 6. Re-optimize | Update the schedule as forecasts, outages, prices, and actual system conditions change. |

### Simplified objective

Minimize: fuel + startup + shutdown + no-load + variable O&M + emissions + reliability penalties

Subject to: load balance, reserves, unit operating limits, ramping, minimum up/down times, fuel and environmental limits, transmission constraints, and contingency requirements.

## 8. Simplified Dispatch Example

Assume system demand is 10,000 MW and transmission constraints do not alter the economic order.

| Resource | Available capacity (MW) | Marginal cost ($/MWh) | Dispatch (MW) |
|---|---|---|---|
| Wind | 2,000 | 0 | 2,000 |
| Nuclear | 3,000 | 10 | 3,000 |
| Coal | 3,000 | 25 | 3,000 |
| Gas combined cycle | 4,000 | 40 | 2,000 |
| Total | 12,000 | — | 10,000 |

The gas combined-cycle resource is the marginal unit because it supplies the final increment needed to meet demand. Its marginal cost is therefore the simplified energy-clearing value in this unconstrained example. Actual market prices may also reflect transmission losses, congestion, reserve scarcity, and market rules.

## 9. How the Modern Resource Mix Changes the Process

- Net-load ramps become more important as solar production falls in the evening.
- Forecast uncertainty increases the value of flexible generation, storage, reserves, and demand response.
- Frequent low or negative marginal-cost periods can lead to renewable curtailment or thermal cycling.
- Storage decisions are intertemporal: charging now is evaluated against the expected value of discharging later.
- Commitment increasingly values flexibility, locational reliability, and ramp capability in addition to fuel efficiency.

## 10. Practical Mental Model

> **Commit, dispatch, and continuously adjust**
>
> Forecast demand and renewable output → commit enough feasible resources to satisfy energy and reserves → dispatch committed resources at the lowest incremental system cost → verify transmission and reliability → re-optimize as conditions change.

In short, unit commitment decides which resources are available, while economic dispatch decides how those available resources are loaded. The least-cost answer is always bounded by reliability and the physical capabilities of the power system.
