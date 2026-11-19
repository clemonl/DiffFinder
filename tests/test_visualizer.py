import json

from difffinder.sorting_visualizer import BUBBLE, SELECTION, compare_sources, record, worker


def test_existing_sort_animations_and_comparison():
    values = [3, -1, 2, 2]
    for source in (BUBBLE, SELECTION):
        result = record(source, 'sort', values)
        assert result['error'] is None
        assert result['output'] == sorted(values)
        assert result['events'][0]['values'] == values
        assert len(result['events']) > 2
    assert compare_sources([(BUBBLE, 'sort'), (SELECTION, 'sort')], values)['same']
    assert values == [3, -1, 2, 2]


def test_comparison_worker_reports_faulty_sort(tmp_path):
    request = tmp_path / 'request.json'
    response = tmp_path / 'response.json'
    request.write_text(json.dumps({'snapshots': [
        ['def sort(arr):\n    return arr\n', 'sort'], [BUBBLE, 'sort']],
        'values': [2, 1]}))
    worker(request, response)
    result = json.loads(response.read_text())
    assert result['same'] is False
    assert result['report']


def test_worker_handles_invalid_source(tmp_path):
    request = tmp_path / 'request.json'
    response = tmp_path / 'response.json'
    request.write_text(json.dumps({'snapshots': [['invalid syntax !', 'sort']], 'values': []}))
    worker(request, response)
    assert 'SyntaxError' in json.loads(response.read_text())['error']
