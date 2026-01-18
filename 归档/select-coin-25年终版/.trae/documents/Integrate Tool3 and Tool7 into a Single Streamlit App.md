# Plan: Integrate Parameter Traversal and Visualization into a Single Tool

I have analyzed `tool3_参数遍历与参数平原图.py` (Data Generator) and `tool7_参数平原可视化.py` (Data Viewer).

**Analysis:**
*   **`tool3` (Generator):** Iterates through a parameter range, generates strategy configurations, runs backtests using the `program` and `core` modules, and saves results to `data/遍历结果`.
*   **`tool7` (Viewer):** A Streamlit app that reads saved results from `data/遍历结果` and generates interactive visualizations (Heatmaps, 3D plots, Sensitivity Analysis).
*   **Integration:** The two tools are complementary. Merging them allows a seamless workflow: **Configure -> Run -> Visualize** in a single interface.

**Proposal:**
I will create a new tool file `tools/tool8_参数平原可视化App.py` (or similar name) that integrates both functionalities using Streamlit.

## Features:
1.  **Unified Interface:** A Streamlit app with two main modes (Sidebar selection):
    *   **🛠️ 运行参数遍历 (Run Traversal):** For generating new data.
    *   **📊 查看分析结果 (View Results):** For visualizing existing data (Logic from `tool7`).

2.  **"Run Traversal" Mode:**
    *   **Strategy Template:** A text area allowing you to define a strategy template (Python dictionary format). You can use a placeholder `{param}` in the code where you want the variable parameter to be.
    *   **Parameter Configuration:** Inputs for `Start`, `End`, and `Step` to define the range for `{param}`.
    *   **Execution:** A "Start Backtest" button that triggers the backend logic (derived from `tool3`). It will show a progress bar and logs.
    *   **Output:** Saves results to `data/遍历结果/{Task Name}`.

3.  **"View Results" Mode:**
    *   Fully integrates the visualization logic from `tool7`.
    *   Allows selecting any folder in `data/遍历结果`.
    *   Displays Parameter Plains, Heatmaps, and 3D Plots.

## Implementation Steps:
1.  **Create `tools/tool8_参数平原可视化App.py`.**
2.  **Import Dependencies:** Combine imports from `tool3` and `tool7`.
3.  **Implement Backend Logic:** Refactor `tool3`'s `find_best_params` and strategy generation loop into a function that can be called by Streamlit. Use `eval()` to parse the user's strategy template with the `{param}` placeholder.
4.  **Implement Frontend Logic:**
    *   Port the visualization code from `tool7`.
    *   Build the input forms for the new "Run" feature.
5.  **Verify:** Ensure the tool can generate a simple test batch and immediately visualize it.

This approach preserves all existing functionality while adding the requested "Run" capability to the frontend.
