import duckdb

con = duckdb.connect("/Users/jakubmarczak/python/music-etl-project/music_pipeline.duckdb")
print(con.execute("SELECT * FROM top_artists LIMIT 20").fetchdf())
con.close()

con = duckdb.connect("/Users/jakubmarczak/python/music-etl-project/music_pipeline.duckdb")
print(con.execute("SELECT * FROM top_tracks LIMIT 20").fetchdf())
con.close()

con = duckdb.connect("/Users/jakubmarczak/python/music-etl-project/music_pipeline.duckdb")
print(con.execute("SELECT * FROM listening_duration LIMIT 20").fetchdf())
con.close()