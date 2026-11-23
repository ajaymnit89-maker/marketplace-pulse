-- One point per zip prefix. The raw table has ~1M rows with several points per prefix and some outside Brazil.
select
    geolocation_zip_code_prefix as zip_code_prefix,
    avg(geolocation_lat) as lat,
    avg(geolocation_lng) as lng
from {{ source('raw', 'geolocation') }}
where geolocation_lat between -34 and 6 and geolocation_lng between -74 and -34
group by 1
