"""One logical quota for private cloud profiles, material originals and papers."""
LIMIT=128*1024*1024

def used(c,uid=None):
    tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    total=0
    for table in ('cloud_devices','learning_profiles','study_materials','qingjuan_papers'):
        if table in tables:
            query='SELECT coalesce(sum(size),0) FROM '+table
            total+=c.execute(query+(' WHERE user_id=?' if uid is not None else ''),(uid,) if uid is not None else ()).fetchone()[0]
    return total
