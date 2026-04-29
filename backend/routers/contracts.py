from fastapi import APIRouter

from repos.repo import Repo
from services.service import Service

router = APIRouter()
repo = Repo()
service = Service(repo)


@router.get("/warranty/check")
async def warranty_check(lat: float, lng: float):
    try:
        return {"status": "success", "data": await service.check_warranty(lat, lng)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/asset/{asset_id}")
async def contracts_for_asset(asset_id: str):
    try:
        contracts = await repo.get_contracts_by_asset(asset_id)
        return {"status": "success", "contracts": contracts, "count": len(contracts)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/{contract_id}")
async def get_contract(contract_id: str):
    try:
        contract = await repo.get_contract_by_id(contract_id)
        return {"status": "success", "contract": contract}
    except Exception as e:
        return {"status": "error", "error": str(e)}
