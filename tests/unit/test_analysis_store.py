import pytest
from retrieval_observatory.store.sqlite import SQLiteStore


@pytest.mark.asyncio
async def test_analysis_records_are_versioned_and_latest_is_listed(tmp_path):
    store = SQLiteStore(str(tmp_path / "analysis.db"))
    await store.init_db()
    await store.save_analysis_record("cohort", "c", {"name": "one"}, 1)
    await store.save_analysis_record("cohort", "c", {"name": "two"}, 2)
    assert (await store.get_analysis_record("cohort", "c"))["name"] == "two"
    assert len(await store.list_analysis_records("cohort")) == 1
    with pytest.raises(ValueError, match="version must be 3"):
        await store.save_analysis_record("cohort", "c", {}, 2)
