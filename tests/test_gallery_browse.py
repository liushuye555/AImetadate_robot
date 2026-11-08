"""The database gallery retains cover -> group -> original navigation."""
from urllib.parse import urlencode
import sqlite3

import pytest

from test_database_gallery import project, add, server, get


def test_groups_are_complete_before_cover_pagination_and_obey_filters(project):
    ids = [add(project, user_id=str(i), sha256=f'sha{i}', prompt_key='workflow') for i in range(65)]
    other = add(project, user_id='other', sha256='other', prompt_key='workflow', scope='group:2')
    single = add(project, user_id='single', sha256='single')
    with server(project) as base:
        query = {'scope': 'group:1', 'page_size': 1}
        first = get(base, '/api/gallery/browse?' + urlencode(query))
        assert first['total'] == 66 and first['group_total'] == 2 and first['has_more']
        second = get(base, '/api/gallery/browse?' + urlencode(query | {'page': 2}))
        cover = second['items'][0]
        assert first['items'][0]['id'] == single
        assert cover['groups'] == [{'key': 'batch:workflow', 'kind': '同批', 'count': 65}]
        group = get(base, '/api/gallery/group?' + urlencode(query | {'key': 'batch:workflow'}))
        assert group['count'] == 65
        assert {item['id'] for item in group['members']} == set(ids)
        assert other not in {item['id'] for item in group['members']}
        assert all('kept_path' not in item and 'sha256' not in item for item in group['members'])
        with pytest.raises(Exception) as exc:
            get(base, '/api/gallery/group?' + urlencode(query | {'key': 'missing'}))
        assert exc.value.code == 404


def test_similar_group_has_priority_but_workflow_still_contains_all_members(project):
    ids = [add(project, user_id=str(i), sha256=f'sha{i}', prompt_key='workflow') for i in range(3)]
    with sqlite3.connect(project / 'data/bot.db') as conn:
        conn.execute('CREATE TABLE view_dhash(path TEXT PRIMARY KEY, mtime INTEGER,size INTEGER,dhash INTEGER,md5 TEXT)')
        for image in ids[:2]:
            conn.execute('INSERT INTO view_dhash VALUES (?,0,0,123,?)',
                         (f'C:\\old\\view-thumbs\\#{image}_800x1200_ai_metadata.jpg', 'same-visual'))
    with server(project) as base:
        result = get(base, '/api/gallery/browse')
        assert result['group_total'] == 2
        similar = next(g for item in result['items'] for g in item['groups'] if g['kind'] == '相似')
        group = get(base, '/api/gallery/group?' + urlencode({'key': similar['key']}))
        assert {item['id'] for item in group['members']} == set(ids[:2])
        workflow = get(base, '/api/gallery/group?key=batch%3Aworkflow')
        assert {item['id'] for item in workflow['members']} == set(ids)


def test_group_routes_reject_duplicate_parameters(project):
    with server(project) as base:
        for route in ('/api/gallery/browse?scope=1&scope=2', '/api/gallery/group?key=a&key=b'):
            with pytest.raises(Exception) as exc:
                get(base, route)
            assert exc.value.code == 400
