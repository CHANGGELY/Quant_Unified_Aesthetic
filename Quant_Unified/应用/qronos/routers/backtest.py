
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any

from service.backtest import backtest_service
from model.model import ResponseModel

router = APIRouter(
    prefix="/backtest",
    tags=["backtest"],
    responses={404: {"description": "Not found"}},
)

class ConfigUpdateRequest(BaseModel):
    content: str

@router.get("/config", response_model=ResponseModel)
async def get_config():
    """Get the current backtest configuration content."""
    try:
        content = backtest_service.get_config_content()
        return ResponseModel.ok(data={"content": content})
    except Exception as e:
        return ResponseModel.error(msg=str(e))

@router.post("/config", response_model=ResponseModel)
async def update_config(request: ConfigUpdateRequest):
    """Update the backtest configuration content."""
    try:
        backtest_service.update_config_content(request.content)
        return ResponseModel.ok(msg="Config updated successfully")
    except Exception as e:
        return ResponseModel.error(msg=str(e))

@router.post("/run", response_model=ResponseModel)
async def run_backtest():
    """Start the backtest process."""
    try:
        result = backtest_service.run_backtest()
        return ResponseModel.ok(data=result)
    except Exception as e:
        return ResponseModel.error(msg=str(e))

@router.get("/status", response_model=ResponseModel)
async def get_status():
    """Get the status of the backtest process."""
    try:
        status = backtest_service.get_status()
        return ResponseModel.ok(data=status)
    except Exception as e:
        return ResponseModel.error(msg=str(e))

@router.get("/logs", response_model=ResponseModel)
async def get_logs():
    """Get the logs of the backtest process."""
    try:
        logs = backtest_service.get_logs()
        return ResponseModel.ok(data=logs)
    except Exception as e:
        return ResponseModel.error(msg=str(e))

@router.get("/reports", response_model=ResponseModel)
async def get_reports():
    """List all available backtest reports."""
    try:
        reports = backtest_service.get_reports()
        return ResponseModel.ok(data=reports)
    except Exception as e:
        return ResponseModel.error(msg=str(e))

from fastapi.responses import FileResponse

@router.get("/report/{report_name}/html")
async def get_report_html(report_name: str):
    """Get the HTML content of a backtest report."""
    try:
        report_path = backtest_service.get_report_html_path(report_name)
        return FileResponse(report_path, media_type="text/html")
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
