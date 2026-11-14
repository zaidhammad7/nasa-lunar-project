// Plain-language explanations shown in tooltips (single source, so wording stays consistent across the dashboard).
export const GLOSSARY = {
  score: 'Site Suitability Score (0-100): 40% terrain safety, 35% solar power, 25% Earth communication (weights change with the priority mode). Higher is better.',
  ci95: "95% confidence interval: the range the true score falls in 95% of the time, given the model's measured error. A narrow range means a more certain score.",
  slope: 'Slope: how steep the ground is, in degrees from flat. Flat (up to 5°) is ideal; above 13.5° the lander risks tipping over (15° limit minus a 1.5° safety margin).',
  sunElevation: "Sun elevation: the Sun's angle above the local horizon, in degrees. Below 0° the Sun is hidden and the panels produce no power. Near the lunar poles it stays within a few degrees of the horizon.",
  earthElevation: "Earth elevation: the Earth's angle above the local horizon. Above 0° the lander has a direct line of sight for communication; below 0° the link is blocked.",
  sunVisible: 'Sunlight: the share of the mission window during which the Sun is above the terrain horizon, including shadows cast by crater walls and mountains.',
  earthVisible: 'Earth comms: the share of the mission window during which Earth is above the terrain horizon, so the lander can talk to Earth directly.',
  horizon: 'Horizon dip: a higher mast sees further over the curved Moon: dip = arccos(R / (R + height)), with R = 1,737.4 km. It lowers the horizon, so the Sun and Earth stay visible longer.',
  tower: 'Tower height: how high the solar panels and antenna sit above the ground (1-150 m). Taller masts see over crater walls but cannot change the ground slope.',
  battery: 'Battery: usable energy storage. The check simulates charging and discharging hour by hour and reports whether the lander survives the longest dark period.',
  unsafe: 'Unsafe for Landing (High Risk): at least one hard safety rule failed (slope too steep, too little sunlight, or no Earth contact), or the worst-case score is too low.',
}
