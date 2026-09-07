"""Execute independent demo kernels and retain readable outputs and an honest report."""
import argparse
import json
import os
from pathlib import Path
import time
import nbformat
from nbclient import NotebookClient

ROOT=Path(__file__).resolve().parents[1]

def execute(path, timeout=1800):
    notebook=nbformat.read(path,as_version=4)
    start=time.monotonic()
    try:
        NotebookClient(notebook,timeout=timeout,kernel_name="epsm-core-demo",resources={"metadata":{"path":str(path.parent)}},store_widget_state=False).execute()
        status="passed"; error=None
    except Exception as exc:
        status="failed"; error=str(exc)
    notebook.metadata.pop("widgets",None)
    # Live model IDs are transient; keep static plots and textual output for git readers.
    for cell in notebook.cells:
        if cell.cell_type=="code":
            outputs=[]
            for output in cell.get("outputs",[]):
                data=output.get("data",{})
                if "application/vnd.jupyter.widget-view+json" in data:
                    continue
                outputs.append(output)
            cell.outputs=outputs
    nbformat.write(notebook,path)
    return {"notebook":str(path.relative_to(ROOT)),"status":status,"seconds":round(time.monotonic()-start,2),"error":error}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("patterns",nargs="*",default=["**/*.ipynb"])
    parser.add_argument("--without-engine",action="store_true")
    parser.add_argument("--report", type=Path, default=ROOT/"output/demo/execution-report.json")
    args=parser.parse_args()
    os.environ.setdefault("MPLBACKEND","module://matplotlib_inline.backend_inline")
    os.environ.setdefault("MPLCONFIGDIR",str(ROOT/"output/demo/.matplotlib"))
    os.environ.setdefault("IPYTHONDIR",str(ROOT/"output/demo/.ipython"))
    report=[]
    paths=sorted({p for pattern in args.patterns for p in (ROOT/'demo').glob(pattern)})
    for path in paths:
        requirements=nbformat.read(path,as_version=4).metadata.epsm_demo.prerequisites
        if args.without_engine and ("EnergyPlus 24.2" in requirements or "local EPW" in requirements):
            report.append({"notebook":str(path.relative_to(ROOT)),"status":"prerequisite_excluded","requirements":requirements})
            continue
        result=execute(path)
        report.append(result)
        print(result['status'],result['notebook'],result['seconds'],flush=True)
        if result['error']: print(result['error'][-2400:],flush=True)
        output=args.report
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,indent=2))
    raise SystemExit(any(r['status']=='failed' for r in report))
