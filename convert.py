import duckdb

duckdb.sql("""
    COPY (
        SELECT * FROM read_csv_auto('accepted_2007_to_2018Q4.csv.gz', sample_size=-1)
    )
    TO 'accepted_2007_to_2018Q4.parquet' (FORMAT PARQUET)
""")

print("Done.")
