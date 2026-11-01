"""Remove owned game files while retaining the complete emulator save directory."""
from pathlib import Path
import shutil
import os
import uuid


def validate_game_id(game_id):
    if not isinstance(game_id,str) or len(game_id)!=64 or any(c not in '0123456789abcdef' for c in game_id):
        raise ValueError('Invalid game identifier')
    return game_id


class GameStorage:
    """Filesystem policy only; player and conversion lifetimes belong to the caller."""

    def __init__(self,library,rendered):
        self.library=Path(library).resolve()
        self.rendered=Path(rendered).resolve()

    @staticmethod
    def _owned(path,parent):
        # Reject redirected game roots and data entries before any recursive
        # removal. shutil.rmtree itself does not traverse nested directory links.
        is_junction = getattr(path, 'is_junction', lambda: False)()
        if path.is_symlink() or is_junction:
            raise ValueError('A linked game folder cannot be deleted from the library.')
        resolved=path.resolve()
        if not resolved.is_relative_to(parent) or resolved==parent:
            raise ValueError('Game data must remain inside its library folder.')
        return path

    def deletion_paths(self,game_id):
        identity=validate_game_id(game_id)
        source=self._owned(self.library/identity,self.library)
        workspace=self._owned(self.rendered/identity,self.rendered)
        if source.is_relative_to(workspace) or workspace.is_relative_to(source):
            raise ValueError('The game library and rendered data folders must be separate.')
        entries=list(workspace.iterdir()) if workspace.exists() else []
        data=[self._owned(entry,workspace) for entry in entries if entry.name.casefold()!='saves']
        # Keep metadata until the other removal steps succeed, so a failed
        # removal can be retried from the library.
        data.sort(key=lambda entry:entry.name=='game.json')
        return source,workspace,data

    @staticmethod
    def _remove(path,parent):
        GameStorage._owned(path,parent)
        if path.is_dir():shutil.rmtree(path)
        elif path.exists():path.unlink()

    def delete(self,game_id):
        source,workspace,_=self.deletion_paths(game_id)
        token=uuid.uuid4().hex
        staged=self.rendered/('.deleting-'+game_id+'-'+token)
        staged_source=self.library/('.deleting-'+game_id+'-'+token)
        backup=self.library/('.deleting-'+token+'.jar')
        metadata=(workspace/'game.json').read_bytes() if (workspace/'game.json').is_file() else None
        moved=False;source_moved=False;committed=False
        try:
            jar=source/'game.jar'
            if jar.is_file():
                # NTFS hard links retain the original bytes without copying a JAR.
                try:os.link(jar,backup)
                except OSError:shutil.copy2(jar,backup)
            if source.exists():source.rename(staged_source);source_moved=True
            if workspace.exists():
                workspace.rename(staged);moved=True
                workspace.mkdir()
                for entry in staged.iterdir():
                    if entry.name.casefold()=='saves':entry.rename(workspace/entry.name)
            self._remove(staged,self.rendered)
            self._remove(staged_source,self.library)
            backup.unlink(missing_ok=True)
            committed=True
        except Exception:
            # Restore the title and original JAR. Files already purged from an
            # artwork cache cannot be undeleted; normal preparation rebuilds them.
            if moved:
                workspace.mkdir(exist_ok=True)
                if staged.exists():
                    for entry in staged.iterdir():entry.rename(workspace/entry.name)
                    staged.rmdir()
                if metadata is not None:(workspace/'game.json').write_bytes(metadata)
            if source_moved:
                if staged_source.exists():staged_source.rename(source)
                if backup.exists():
                    source.mkdir(exist_ok=True)
                    if not (source/'game.jar').exists():os.replace(backup,source/'game.jar')
            raise
        finally:
            if committed or (source/'game.jar').is_file():
                try:backup.unlink(missing_ok=True)
                except OSError:pass
        if workspace.is_dir() and not any(workspace.iterdir()):
            try:workspace.rmdir()
            except OSError:pass
        return workspace/'saves'
