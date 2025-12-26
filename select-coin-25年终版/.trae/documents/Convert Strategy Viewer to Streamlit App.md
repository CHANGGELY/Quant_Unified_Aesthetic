# Plan to Convert Tool3 into a Streamlit App

I will transform `tools/tool3_策略查看器.py` into an interactive Streamlit application. This will allow you to run the backtest once and then freely explore the results with different filtering and sorting options without restarting the script.

## 1. File Modification

I will modify `f:\量化币圈\邢不行研究小组第39期：1号择时策略小组-2025\select-coin-25年终版\tools\tool3_策略查看器.py`.

## 2. Implementation Details

### A. Imports and Setup

* Import `streamlit` and necessary Plotly libraries.

* Keep the project path setup to ensure imports work correctly.

### B. Data Loading with Caching (Optimization)

* Implement a `load_data()` function decorated with `@st.cache_data`.

* This function will:

  1. Load the `config.py` configuration.
  2. Load `final_select_results.pkl` (Backtest results).
  3. Load `candle_data_dict.pkl` (K-line data).
  4. Run `PeriodGenerator` and `MetricsCalculator` once to process the raw data into analyzed periods.

* This ensures that changing filters (like "Sort by Return") is instant and doesn't reload the heavy data files.

### C. Interactive Sidebar (Configuration)

I will create Streamlit widgets in the sidebar for all `STRATEGY_VIEWER_CONFIG` parameters:

* **Selection Mode**: Dropdown (`rank`, `pct`, `val`, `symbol`).

* **Metric Type**: Dropdown (`return`, `max_drawdown`, etc.).

* **Sort Direction**: Dropdown (`desc`, `asc`, `auto`).

* **Selection Value**: Dynamic inputs based on the chosen mode:

  * `rank`: Number inputs for start and end rank.

  * `pct` / `val`: Range slider or float inputs.

  * `symbol`: Multiselect box (populated with all available symbols from the data).

* **Chart Days**: Input for display range.

* **Show Volume**: Checkbox.

### D. Visualization

* I will adapt the logic from `HTMLReporter` to render directly in Streamlit:

  * **Summary Stats**: Use `st.metric` to show Total Trades, Win Rate, Avg Return, etc.

  * **Charts**: Use `st.plotly_chart` to display the K-line charts interactively. I will extract the chart generation logic so it returns a Plotly Figure object instead of an HTML string.

  * **Details**: Display trade details (Entry/Exit time, Return, etc.) alongside the charts.

## 3. Execution

* You will run the tool using: `streamlit run tools/tool3_策略查看器.py` (I will provide the command).

* The script will detect if it's running in Streamlit and render the UI.

## 4. Verification

* I will verify that the app loads the data correctly.

* I will verify that the interactive filters work as expected.

