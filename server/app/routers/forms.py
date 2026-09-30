from fastapi import APIRouter, Depends, HTTPException

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
