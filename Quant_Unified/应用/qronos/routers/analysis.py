
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from service.analysis import analysis_service
from model.model import ResponseModel

router = APIRouter(
    prefix="/analysis",
    tags=["analysis"],
    responses={404: {"description": "Not found"}},
)

@router.post("/factor/run", response_model=ResponseModel)
async def run_factor_analysis():
    """运行因子分析"""
    try:
        logs = analysis_service.run_factor_analysis()
        return ResponseModel.ok(data={"logs": logs})
    except Exception as e:
        return ResponseModel.error(msg=str(e))

@router.get("/factor/reports", response_model=ResponseModel)
async def get_factor_reports():
    """获取因子分析报告列表"""
    try:
        reports = analysis_service.get_factor_reports()
        return ResponseModel.ok(data=reports)
    except Exception as e:
        return ResponseModel.error(msg=str(e))

@router.get("/factor/report/{report_name}/html")
async def get_factor_report_html(report_name: str):
    """获取因子分析报告HTML"""
    try:
        path = analysis_service.get_factor_report_path(report_name)
        return FileResponse(path)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/similarity/run", response_model=ResponseModel)
async def run_similarity_analysis():
    """运行选币相似度分析"""
    try:
        logs = analysis_service.run_similarity_analysis()
        return ResponseModel.ok(data={"logs": logs})
    except Exception as e:
        return ResponseModel.error(msg=str(e))

@router.get("/similarity/report/html")
async def get_similarity_report_html():
    """获取选币相似度分析报告HTML"""
    try:
        path = analysis_service.get_similarity_report_path()
        return FileResponse(path)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/correlation/run", response_model=ResponseModel)
async def run_correlation_analysis():
    """运行资金曲线涨跌幅对比分析"""
    try:
        logs = analysis_service.run_correlation_analysis()
        return ResponseModel.ok(data={"logs": logs})
    except Exception as e:
        return ResponseModel.error(msg=str(e))

@router.get("/correlation/report/html")
async def get_correlation_report_html():
    """获取资金曲线涨跌幅对比分析报告HTML"""
    try:
        path = analysis_service.get_correlation_report_path()
        return FileResponse(path)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
