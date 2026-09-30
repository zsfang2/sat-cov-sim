# Explorer JSON API v1

默认地址 `http://127.0.0.1:8766`；仅监听回环地址。API 不提供 HTML、CSS 或 JavaScript，仿真包不依赖展示目录。独立前端用固定目标代理将 `/api/*` 转发过来。

GET `/api/health` 返回 `{"service":"satellite-coverage-sim","api_version":1,"status":"ready",...}`。前端必须检查 `api_version`，不能只根据页面能打开判定后端兼容。

所有 POST 使用 JSON 对象，携带 `Content-Type: application/json`、`X-Explorer: 1`。默认错误响应为 HTTP 400 和 `{"error":"原因"}`；未知路由 404；Host/Origin 不合法 403。前端代理在后端无法连接时返回 502。不得把错误 JSON 当作空窗口结果。

| 方法 / 路径 | 输入 | 主要输出 |
| --- | --- | --- |
| GET `/api/defaults` | 无 | 数据根目录、存在的示例路径、默认点位与时间 |
| GET `/api/browse` | query: `path`, `kind=tle/dem` | 目录路径、父目录和文件列表；限制在后端数据根目录 |
| POST `/api/catalog` | `{"path":"服务器路径"}` 或 `{"text":"TLE内容","name":"文件名"}` | `catalog_id`、记录/卫星数量、历元范围和卫星目录 |
| POST `/api/visibility` | 见下方例子 | `job_id`；异步计算 |
| GET `/api/job?id=...` | 任务 ID | `state`、进度；完成后提供 `result`，失败提供 `error` |
| POST `/api/cancel` | `job_id` | 取消请求状态；通过 job 接口确认最终取消 |
| POST `/api/track` | `job_id`, `norad_id`, 可选 `point_index` | 单个采样点的 721 个显示采样及星下点轨迹 |
| POST `/api/dem-info` | `path` | CRS、范围、栅格尺寸、单位及垂直条件状态 |
| POST `/api/dem` | `path`, `bounds:[西,南,东,北]`, 可选 `size` | 扁平像元数组、nodata=`null`、显示范围和元数据 |

单点任务示例：

```json
{
  "catalog_id": "先前解析返回的 ID",
  "start": "2025-01-01T00:00:00Z",
  "end": "2025-01-01T02:00:00Z",
  "observer": {"mode": "point", "lon": 108.9016839, "lat": 34.2427189, "height_m": 0},
  "min_elevation_deg": 10,
  "max_age_days": 7,
  "region_rule": "any",
  "satellite_ids": null
}
```

区域将 `observer` 替换为 `{"mode":"region","bounds":[108.8,34.1,109.0,34.3],"grid":3,"height_m":0}`。`region_rule` 为 `any` 或 `all`，默认 `any`；`satellite_ids=null` 表示全部，不是自动截取前若干颗。

`height_m` 为 WGS-84 椭球高；时间必须有时区；单次最多七天。`result.complete=false` 表示有跳过/失败，不能据此声称所有卫星都不可见。窗口包含 UTC 起止、秒时长、边界截断以及所选 TLE 身份；完整结果保留逐点窗口、选星历元政策和后端源码哈希。

计算政策与 DEM 适用范围详见 [EXPLORER.md](EXPLORER.md)。前端仅展示状态，不重定义区域聚合、历元选择或可见性算法。若未来改变字段含义、必填输入或状态语义，应升级接口主版本并同时更新前端联调。
