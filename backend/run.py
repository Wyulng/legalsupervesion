import uvicorn, sys
from pathlib import Path

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "batch":
        # 批量处理模式：直接调用 process_batch 处理指定目录下的判决书文件
        from app.main import process_batch, save_results_to_csv

        case_dir = Path(__file__).parent / "batch_cases"
        if len(sys.argv) > 2:
            case_dir = Path(sys.argv[2])

        case_dir.mkdir(exist_ok=True)
        files = sorted(case_dir.glob("*.doc")) + sorted(case_dir.glob("*.DOC")) + sorted(case_dir.glob("*.docx"))
        if not files:
            print(f"目录 {case_dir} 中没有找到判决书文件（.doc/.DOC/.docx）")
            sys.exit(1)

        print(f"找到 {len(files)} 个文件: {[f.name for f in files]}\n")
        results = process_batch(files)

        print(f"\n{'='*60}")
        for r in results:
            print(f"\n文件: {r.filename}")
            for model, key in [("M1", "model1"), ("M5", "model5"), ("M10", "model10"), ("M3", "model3")]:
                cand = getattr(r, f"{key}_candidate")
                status = getattr(r, f"{key}_status")
                issue = getattr(r, f"{key}_issue")
                reason = getattr(r, f"{key}_reason")
                risk = getattr(r, f"{key}_risk", "")
                print(f"  {model}: candidate={cand} status={status} issue={issue} risk={risk}")
                if reason:
                    print(f"    reason: {reason[:100]}{'...' if len(reason) > 100 else ''}")
                # M3 增强字段
                if key == "model3":
                    scene = getattr(r, f"{key}_scene_type", "")
                    exp_time = getattr(r, f"{key}_expected_time_type", "")
                    act_time = getattr(r, f"{key}_actual_time_type", "")
                    t_match = getattr(r, f"{key}_time_type_match", "")
                    r_match = getattr(r, f"{key}_reason_match", "")
                    if scene:
                        print(f"    scene_type={scene} expected={exp_time} actual={act_time} time_match={t_match} reason_match={r_match}")

        csv_path = case_dir / "batch_results.csv"
        save_results_to_csv(results, csv_path)
        print(f"\n结果已保存到: {csv_path}")
        print(f"\n处理完成 {len(results)}/{len(files)} 个文件")
    else:
        uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)