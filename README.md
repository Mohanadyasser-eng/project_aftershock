Project Aftershock: Regional Seismic Risk Triage

This project builds an automated first-pass triage system for recent seismic events. By pulling a live feed from the USGS catalog and reconciling it against internal sensor logs, the pipeline flags which events warrant an immediate regional loss estimate and which can wait for routine manual review.

Resources and Data
The pipeline relies on the USGS Earthquake Catalog API (FDSN Event query endpoint) and a locally generated regional_sensor_log.csv file. The USGS API is fully public domain, requiring zero authentication or sign-up. To respect rate limits, the script pulls the data using a single, well-scoped query rather than a polling loop. Setup and execution take roughly 3 to 5 hours.

Target Definition
To determine if an event is significant, we use this explicit formula:
significant = 1 if magnitude >= 5.0
significant = 0 otherwise

We use 5.0 because it is the seismological floor for a moderate earthquake. If we used the 8.0+ great threshold, the events would be so rare that a two-week data pull might return zero targets, making downstream validation impossible.

Extracted and Engineered Features
To support the triage flag, we extracted and engineered the following features:

1) mag: The earthquake magnitude.
2) depth_km: The depth of the event.
3) sig: The USGS composite significance score.
4) felt: The number of felt reports.
5) gap: The azimuthal gap, used as a proxy for data quality.
6) type: The event type, used to filter out explosions and quarry blasts.
7) region: Parsed from the unstructured place text.
8) depth_category: An engineered bucket (shallow, intermediate, or deep).

Business ROI
If only significant == 1 events auto-generate a loss-estimate ticket, manual adjuster review volume drops by 91.28%.
(Calculated using a total of 2639 records, with 230 flagged as significant.)

Validation
As a quick validation check, the pipeline calculates the average USGS significance score (sig) for both flagged and unflagged groups. The average sig for significant == 1 records is 436.42, compared to just 225.92 for significant == 0 records. This roughly 2x gap confirms the flag is working as intended: the 5.0 magnitude threshold is picking out events that USGS's own independently-computed composite score also treats as materially more significant, even though sig factors in things like felt reports and CDI/MMI intensity that magnitude alone does not. The two measures agreeing gives confidence that the triage flag is capturing real impact, not just an arbitrary magnitude cutoff.

Imputation Strategy
felt and cdi are imputed as 0 when missing, because a null there plausibly means "no felt reports were logged," which is a legitimate zero rather than missing information. gap, dmin, and nst are imputed with the cohort median instead, because a null there means "station network quality is unknown" — assuming zero would understate the azimuthal gap and distort the data-quality signal those fields are meant to carry.