from pathlib import Path
import threading
from unittest.mock import Mock

import pytest
from PIL import Image

from runtime_assets.resources import GIB,MIB,PreparationBudget,ResourcePressure,plan_budget,budget_violation
from runtime_assets.backends import PixelBackend
from runtime_assets.contracts import pixel_recipe


def test_dedicated_memory_and_host_headroom_enable_bounded_large_batches():
    budget=plan_budget({'kind':'dedicated','device_local_bytes':4*GIB},3*GIB,8,gpu_free=4*GIB)
    assert budget.max_images==512 and budget.max_pixels==1_048_576
    assert budget.processing_threads==2 and budget.gpu_budget_bytes==2*GIB
    assert budget.gpu_reserve_bytes==512*MIB and not budget.reason


def test_lower_vram_and_cpu_count_choose_a_smaller_execution_plan():
    budget=plan_budget({'kind':'dedicated','device_local_bytes':2*GIB},3*GIB,2,gpu_free=2*GIB)
    assert budget.max_images==128 and budget.processing_threads==1
    assert budget.gpu_budget_bytes==GIB


def test_memory_pressure_defers_instead_of_saturating_the_device():
    device={'kind':'dedicated','device_local_bytes':4*GIB}
    assert plan_budget(device,GIB,8,gpu_free=4*GIB).reason
    assert plan_budget(device,3*GIB,8,gpu_free=200*MIB).reason
    assert plan_budget(None,256*MIB,8).reason


def test_integrated_gpu_uses_shared_ram_budget_and_one_processing_thread():
    device={'kind':'integrated','device_local_bytes':2*GIB}
    assert plan_budget(device,GIB,8).reason
    budget=plan_budget(device,3*GIB,8)
    assert budget.max_images==256 and budget.processing_threads==1
    assert budget.gpu_budget_bytes==768*MIB
    assert plan_budget(device,9*GIB//4,8).max_images==64


def test_memory_watchdog_keeps_existing_gpu_usage_out_of_its_allocation_delta():
    budget=PreparationBudget(512,1_048_576,2,2*GIB,512*MIB)
    assert not budget_violation(budget,3*GIB,{'used_bytes':3*GIB,'free_bytes':GIB},GIB)
    assert budget_violation(budget,3*GIB,{'used_bytes':3*GIB+MIB,'free_bytes':GIB},GIB)
    assert budget_violation(budget,3*GIB,{'used_bytes':GIB,'free_bytes':100*MIB},GIB)
    assert budget_violation(budget,100*MIB,None,0)


def test_cpu_backend_defers_large_work_before_running_the_scaler(monkeypatch):
    monkeypatch.setattr('runtime_assets.resources.host_memory',lambda:{'available_bytes':128*MIB})
    scale=Mock()
    with pytest.raises(ResourcePressure):
        PixelBackend(scale).enhance(Image.new('RGBA',(1024,1024)),pixel_recipe(),Path('.'))
    scale.assert_not_called()


def test_cpu_backend_still_prepares_small_images_with_one_call(monkeypatch):
    monkeypatch.setattr('runtime_assets.resources.host_memory',lambda:{'available_bytes':128*MIB})
    scale=Mock(side_effect=lambda image:image.resize((image.width*4,image.height*4)))
    result=PixelBackend(scale).enhance(Image.new('RGBA',(8,10)),pixel_recipe(),Path('.'))
    assert result.size==(32,40) and scale.call_count==1


def test_ai_is_not_selected_by_default_without_a_compatible_device(monkeypatch):
    import ai_backend
    monkeypatch.setattr(ai_backend,'executable',lambda:Path('present.exe'))
    monkeypatch.setattr('gpu_policy.devices',lambda:[])
    assert not ai_backend.available()


def test_guard_stops_its_model_process_when_gpu_memory_grows_past_budget(monkeypatch):
    from runtime_assets.resources import ModelMemoryGuard
    stopped=threading.Event()
    process=Mock()
    process.poll.return_value=None
    process.terminate.side_effect=stopped.set
    monkeypatch.setattr('runtime_assets.resources.host_memory',lambda:{'available_bytes':3*GIB})
    monkeypatch.setattr('runtime_assets.resources.gpu_memory',lambda device:
                        {'used_bytes':3*GIB+MIB,'free_bytes':GIB})
    guard=ModelMemoryGuard(process,{'kind':'dedicated'},
                           PreparationBudget(512,1_048_576,2,2*GIB,512*MIB),baseline_used=GIB)
    guard.start()
    try:
        assert stopped.wait(2)
        assert guard.reason and guard.peak_extra_bytes==2*GIB+MIB
        process.terminate.assert_called_once()
    finally:guard.close()
    assert not guard.thread.is_alive()


def test_guard_can_close_without_terminating_a_healthy_model_process(monkeypatch):
    from runtime_assets.resources import ModelMemoryGuard
    sampled=threading.Event()
    process=Mock()
    process.poll.return_value=None
    def memory(device):
        sampled.set()
        return {'used_bytes':GIB,'free_bytes':3*GIB}
    monkeypatch.setattr('runtime_assets.resources.host_memory',lambda:{'available_bytes':3*GIB})
    monkeypatch.setattr('runtime_assets.resources.gpu_memory',memory)
    guard=ModelMemoryGuard(process,{'kind':'dedicated'},
                           PreparationBudget(512,1_048_576,2,2*GIB,512*MIB),baseline_used=0)
    guard.start()
    try:assert sampled.wait(2)
    finally:guard.close()
    process.terminate.assert_not_called()
    assert not guard.reason and not guard.thread.is_alive()


def test_inference_rechecks_processing_limit_immediately_before_launch(tmp_path,monkeypatch):
    import ai_backend
    process=Mock(returncode=0)
    process.communicate.return_value=('','')
    launch=Mock(return_value=process)
    guard=Mock(reason='',peak_extra_bytes=0)
    monkeypatch.setattr(ai_backend.subprocess,'Popen',launch)
    monkeypatch.setattr('gpu_policy.inference_arguments',lambda:([],None))
    monkeypatch.setattr('runtime_assets.resources.current_budget',lambda:PreparationBudget(128,524_288,1))
    monkeypatch.setattr('runtime_assets.resources.gpu_memory',lambda device:None)
    monkeypatch.setattr('runtime_assets.resources.ModelMemoryGuard',lambda *args,**kwargs:guard)
    ai_backend._run(Path('model.exe'),tmp_path/'input',tmp_path/'output',tmp_path,
                    processing_threads=2,count=128)
    command=launch.call_args.args[0]
    assert command[command.index('-j')+1]=='1:1:1'
    guard.start.assert_called_once()
    guard.close.assert_called_once()
