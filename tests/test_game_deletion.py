import io
import threading
import zipfile
from unittest.mock import Mock

import pytest
from PIL import Image

from engine import Library
from game_storage import GameStorage


GAME='a'*64
OTHER='b'*64


def test_storage_removes_game_data_and_preserves_all_saves_and_other_games(tmp_path):
    library=tmp_path/'library';rendered=tmp_path/'rendered'
    source=library/GAME;workspace=rendered/GAME
    source.mkdir(parents=True)
    (source/'game.jar').write_bytes(b'imported game')
    (library/'settings.json').write_text('{}')
    external=tmp_path/'download.jar';external.write_bytes(b'original download')
    for folder in ('textures','textures-ai','textures-cache/recipe','captures','.runtime/events','logs','saves/nested'):
        (workspace/folder).mkdir(parents=True)
        (workspace/folder/'data.bin').write_bytes(folder.encode())
    (workspace/'saves/progress.rms').write_bytes(b'player progress')
    (workspace/'game.json').write_text('{}')
    (workspace/'asset-cache.sqlite').write_bytes(b'cache database')
    (rendered/OTHER).mkdir()
    (rendered/OTHER/'game.json').write_text('other game')
    saves={p.relative_to(workspace/'saves'):p.read_bytes() for p in (workspace/'saves').rglob('*') if p.is_file()}
    store=GameStorage(library,rendered)

    assert store.delete(GAME)==workspace/'saves'

    assert list(workspace.iterdir())==[workspace/'saves']
    assert {p.relative_to(workspace/'saves'):p.read_bytes() for p in (workspace/'saves').rglob('*') if p.is_file()}==saves
    assert not source.exists()
    assert external.read_bytes()==b'original download'
    assert (library/'settings.json').exists()
    assert (rendered/OTHER/'game.json').read_text()=='other game'
    store.delete(GAME)  # Repeating deletion must still leave the saves alone.
    assert (workspace/'saves/progress.rms').read_bytes()==b'player progress'


@pytest.mark.parametrize('identity',['../outside','0'*63,'F'*64,None])
def test_invalid_game_paths_are_rejected_before_removing_files(tmp_path,identity):
    sentinel=tmp_path/'keep.txt';sentinel.write_text('keep')
    with pytest.raises(ValueError):GameStorage(tmp_path/'lib',tmp_path/'rendered').delete(identity)
    assert sentinel.read_text()=='keep'


def test_overlapping_roots_are_rejected_before_any_removal(tmp_path):
    source=tmp_path/GAME;workspace=source/GAME
    (workspace/'saves').mkdir(parents=True)
    (workspace/'saves/progress').write_text('keep')
    with pytest.raises(ValueError):GameStorage(tmp_path,source).delete(GAME)
    assert (workspace/'saves/progress').read_text()=='keep'


def test_linked_game_root_is_rejected_without_following_it(tmp_path,monkeypatch):
    source=tmp_path/'lib'/GAME;source.mkdir(parents=True)
    sentinel=source/'game.jar';sentinel.write_text('keep')
    original=type(source).is_junction
    monkeypatch.setattr(type(source),'is_junction',lambda path:path==source or original(path))
    with pytest.raises(ValueError):GameStorage(tmp_path/'lib',tmp_path/'rendered').delete(GAME)
    assert sentinel.read_text()=='keep'


def test_empty_game_without_saves_is_removed_without_creating_data(tmp_path):
    workspace=tmp_path/'rendered'/GAME;workspace.mkdir(parents=True)
    (workspace/'game.json').write_text('{}')
    GameStorage(tmp_path/'lib',tmp_path/'rendered').delete(GAME)
    assert not workspace.exists()


def test_delete_and_reimport_reuses_save_bytes_and_rebuilds_artwork(tmp_path):
    library=Library(tmp_path/'lib',tmp_path/'rendered')
    source=tmp_path/'test.jar'
    png=io.BytesIO();Image.new('RGBA',(4,5),'red').save(png,format='PNG')
    with zipfile.ZipFile(source,'w') as jar:
        jar.writestr('META-INF/MANIFEST.MF','MIDlet-Name: Delete test\nMIDlet-1: Delete test,,Test\n')
        jar.writestr('image.png',png.getvalue())
    original=source.read_bytes()
    try:
        game=library.import_game(source)
        folder=library.workspace(game['id'])
        save=folder/'saves/freej2me_system/rms/player.dat';save.parent.mkdir(parents=True)
        save.write_bytes(b'level 7 progress')
        library.delete_game(game['id'])
        assert library.games()==[]
        assert list(folder.iterdir())==[folder/'saves']
        with pytest.raises(KeyError):library.asset_service.stats(game['id'])
        # Force another coordinator cycle: no cached snapshot may recreate data.
        with library.asset_service._coordinator_gate:library.asset_service._coordinate_once()
        assert list(folder.iterdir())==[folder/'saves']
        again=library.import_game(source)
        assert again['id']==game['id'] and again['status']=='Ready'
        assert save.read_bytes()==b'level 7 progress'
        assert source.read_bytes()==original
        assert (library.library/game['id']/'game.jar').is_file()
        assert (folder/'original-assets').is_dir()
        assert library.asset_service.stats(game['id'])['sources']==1
    finally:library.asset_service.close(timeout=5)


def test_running_player_prevents_deletion_even_without_a_registered_service(tmp_path):
    library=Library(tmp_path/'lib',tmp_path/'rendered')
    folder=library.workspace(GAME);(folder/'saves').mkdir(parents=True)
    (folder/'game.json').write_text('{}')
    (folder/'saves/progress').write_bytes(b'keep')
    player=Mock();player.poll.return_value=None
    library._players[GAME]=player
    try:
        with pytest.raises(RuntimeError,match='Close the game'):library.delete_game(GAME)
        assert (folder/'game.json').is_file() and (folder/'saves/progress').read_bytes()==b'keep'
        player.terminate.assert_not_called()
    finally:library.asset_service.close()


def test_cleanup_failure_restores_original_jar_metadata_and_saves(tmp_path,monkeypatch):
    source=tmp_path/'lib'/GAME;source.mkdir(parents=True)
    (source/'game.jar').write_bytes(b'original jar')
    workspace=tmp_path/'rendered'/GAME
    (workspace/'saves').mkdir(parents=True)
    (workspace/'saves/progress').write_bytes(b'level 7')
    (workspace/'game.json').write_bytes(b'{"name":"Game"}')
    (workspace/'texture.png').write_bytes(b'disposable cache')
    real=GameStorage._remove
    def fail_after_partial_cleanup(path,parent):
        if parent==workspace.parent:
            (path/'texture.png').unlink()
            raise OSError('simulated file lock')
        real(path,parent)
    monkeypatch.setattr(GameStorage,'_remove',staticmethod(fail_after_partial_cleanup))
    with pytest.raises(OSError,match='file lock'):GameStorage(tmp_path/'lib',workspace.parent).delete(GAME)
    assert (source/'game.jar').read_bytes()==b'original jar'
    assert (workspace/'game.json').read_bytes()==b'{"name":"Game"}'
    assert (workspace/'saves/progress').read_bytes()==b'level 7'
    assert not list(workspace.parent.glob('.deleting-*'))
    assert not list(source.parent.glob('.deleting-*'))


def test_deletions_of_different_games_overlap_without_holding_library_lock(tmp_path,monkeypatch):
    library=Library(tmp_path/'lib',tmp_path/'rendered')
    entered=threading.Barrier(3,timeout=5);release=threading.Event();errors=[]
    def slow_delete(storage,identity):
        entered.wait();assert release.wait(5)
        return library.workspace(identity)/'saves'
    monkeypatch.setattr(GameStorage,'delete',slow_delete)
    def delete(identity):
        try:library.delete_game(identity)
        except Exception as error:errors.append(error)
    threads=[threading.Thread(target=delete,args=(identity,)) for identity in (GAME,OTHER)]
    try:
        for thread in threads:thread.start()
        entered.wait()
        assert library.lock.acquire(timeout=0.2)
        library.lock.release()
        library.save({'id':'c'*64,'name':'Unrelated game'})
        with pytest.raises(RuntimeError,match='being deleted'):library.save({'id':GAME})
        with pytest.raises(RuntimeError,match='being deleted'):library.launch({'id':GAME})
    finally:
        release.set()
        for thread in threads:thread.join(5)
        library.asset_service.close()
    assert not errors and not library._deleting
