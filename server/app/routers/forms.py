from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..auth import get_current_user
from ..config import Settings, get_settings
from ..content import Form, get_forms
from ..schemas import FormSummary

router = APIRouter(prefix="/forms", tags=["forms"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[FormSummary])
def list_forms(settings: Settings = Depends(get_settings)) -> list[FormSummary]:
    forms = get_forms(str(settings.content_dir))
    return [
        FormSummary(
            id=f.id,
            version=f.version,
            kind=f.kind,
            title=f.title.model_dump(),
            task_count=len(f.tasks),
            item_count=sum(len(t.items) for t in f.tasks),
        )
        for f in forms.values()
    ]


@router.get("/{form_id}", response_model=Form)
def get_form(form_id: str, settings: Settings = Depends(get_settings)) -> Form:
    forms = get_forms(str(settings.content_dir))
    if form_id not in forms:
        raise HTTPException(404, "unknown form")
    return forms[form_id]


@router.get("/{form_id}/audio/{path:path}", include_in_schema=True)
def form_audio(form_id: str, path: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    """Prompt audio for an item (content/audio/...). Path must be declared by an item of the form."""
    forms = get_forms(str(settings.content_dir))
    form = forms.get(form_id)
    if form is None:
        raise HTTPException(404, "unknown form")
    declared = {i.audio for t in form.tasks for i in t.items if i.audio} | {
        t.audio for t in form.tasks if t.audio
    }
    if path not in declared:
        raise HTTPException(404, "audio not declared by this form")
    file = (Path(settings.content_dir) / path).resolve()
    if not str(file).startswith(str(Path(settings.content_dir).resolve())) or not file.is_file():
        raise HTTPException(404, "audio file missing (run content/build_audio.py)")
    return FileResponse(file, media_type="audio/wav")
