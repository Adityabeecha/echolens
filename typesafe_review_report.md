# TypeSafe review report

259 completed requests cover 184 eligible files, not exhaustive application verification. 131 lines in 32 files were blanked by credential screening. Empty files, frontend/src/tokens.css and frontend/src/vite-env.d.ts were excluded by the reused scanner. Browser end-to-end, live integrations, and PostgreSQL were not tested.

Complete coverage: True. Planned requests: 259. Attempted requests: 259.

AI classifications, not verified defects. Flow review uses bounded excerpts, not exhaustive path analysis. Confidence is per answer, never a combined file probability.

## 1: .gitignore

Scope: file; status: reviewed.

- Lines 1–53 (.gitignore)
- runtime_error_risk: not_detected (confidence 0.360; detected probability 0.010)
- correctness_risk: insufficient_context (confidence 0.530; detected probability 0.000)
- security_risk: not_detected (confidence 0.340; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.460; detected probability 0.060)
- no_major_issue: not_detected (confidence 0.240; detected probability 0.080)

## 2: backend/Dockerfile

Scope: file; status: reviewed.

- Lines 1–33 (backend/Dockerfile)
- runtime_error_risk: not_detected (confidence 0.220; detected probability 0.210)
- correctness_risk: not_detected (confidence 0.050; detected probability 0.270)
- security_risk: detected (confidence 0.210; detected probability 0.480)
- maintainability_risk: detected (confidence 0.160; detected probability 0.440)
- no_major_issue: detected (confidence 0.060; detected probability 0.370)

## 3: backend/echolens/__init__.py

Scope: file; status: reviewed.

- Lines 1–3 (backend/echolens/__init__.py)
- runtime_error_risk: not_detected (confidence 0.470; detected probability 0.000)
- correctness_risk: insufficient_context (confidence 0.810; detected probability 0.000)
- security_risk: insufficient_context (confidence 0.660; detected probability 0.000)
- maintainability_risk: insufficient_context (confidence 0.410; detected probability 0.000)
- no_major_issue: insufficient_context (confidence 0.450; detected probability 0.100)

## 4: backend/echolens/api/app.py

Scope: file; status: reviewed.

- Lines 1–398 (backend/echolens/api/app.py)
- runtime_error_risk: detected (confidence 0.420; detected probability 0.610)
- correctness_risk: detected (confidence 0.250; detected probability 0.510)
- security_risk: insufficient_context (confidence 0.710; detected probability 0.100)
- maintainability_risk: detected (confidence 0.630; detected probability 0.760)
- no_major_issue: detected (confidence 0.150; detected probability 0.440)

## 5: backend/echolens/api/app.py

Scope: file; status: reviewed.

- Lines 399–807 (backend/echolens/api/app.py)
- runtime_error_risk: detected (confidence 0.740; detected probability 0.820)
- correctness_risk: detected (confidence 0.350; detected probability 0.560)
- security_risk: not_detected (confidence 0.210; detected probability 0.340)
- maintainability_risk: detected (confidence 0.520; detected probability 0.680)
- no_major_issue: detected (confidence 0.310; detected probability 0.540)

## 6: backend/echolens/api/app.py

Scope: file; status: reviewed.

- Lines 808–1196 (backend/echolens/api/app.py)
- runtime_error_risk: detected (confidence 0.340; detected probability 0.560)
- correctness_risk: detected (confidence 0.170; detected probability 0.450)
- security_risk: insufficient_context (confidence 0.090; detected probability 0.330)
- maintainability_risk: detected (confidence 0.460; detected probability 0.630)
- no_major_issue: detected (confidence 0.090; detected probability 0.390)

## 7: backend/echolens/api/app.py

Scope: file; status: reviewed.

- Lines 1197–1591 (backend/echolens/api/app.py)
- runtime_error_risk: detected (confidence 0.350; detected probability 0.570)
- correctness_risk: detected (confidence 0.380; detected probability 0.590)
- security_risk: detected (confidence 0.220; detected probability 0.480)
- maintainability_risk: detected (confidence 0.620; detected probability 0.750)
- no_major_issue: detected (confidence 0.100; detected probability 0.400)

## 8: backend/echolens/api/app.py

Scope: file; status: reviewed.

- Lines 1592–1997 (backend/echolens/api/app.py)
- runtime_error_risk: detected (confidence 0.550; detected probability 0.700)
- correctness_risk: insufficient_context (confidence 0.130; detected probability 0.360)
- security_risk: not_detected (confidence 0.060; detected probability 0.260)
- maintainability_risk: detected (confidence 0.390; detected probability 0.590)
- no_major_issue: detected (confidence 0.110; detected probability 0.400)

## 9: backend/echolens/api/app.py

Scope: file; status: reviewed.

- Lines 1998–2388 (backend/echolens/api/app.py)
- runtime_error_risk: detected (confidence 0.480; detected probability 0.650)
- correctness_risk: detected (confidence 0.630; detected probability 0.750)
- security_risk: detected (confidence 0.430; detected probability 0.620)
- maintainability_risk: detected (confidence 0.640; detected probability 0.760)
- no_major_issue: detected (confidence 0.340; detected probability 0.560)

## 10: backend/echolens/api/app.py

Scope: file; status: reviewed.

- Lines 2389–2772 (backend/echolens/api/app.py)
- runtime_error_risk: detected (confidence 0.630; detected probability 0.760)
- correctness_risk: detected (confidence 0.460; detected probability 0.640)
- security_risk: insufficient_context (confidence 0.470; detected probability 0.150)
- maintainability_risk: detected (confidence 0.630; detected probability 0.750)
- no_major_issue: detected (confidence 0.300; detected probability 0.540)

## 11: backend/echolens/api/app.py

Scope: file; status: reviewed.

- Lines 2773–3147 (backend/echolens/api/app.py)
- runtime_error_risk: detected (confidence 0.560; detected probability 0.700)
- correctness_risk: detected (confidence 0.940; detected probability 0.960)
- security_risk: insufficient_context (confidence 0.120; detected probability 0.290)
- maintainability_risk: detected (confidence 0.970; detected probability 0.980)
- no_major_issue: detected (confidence 0.730; detected probability 0.820)

## 12: backend/echolens/ask.py

Scope: file; status: reviewed.

- Lines 1–193 (backend/echolens/ask.py)
- runtime_error_risk: detected (confidence 0.400; detected probability 0.600)
- correctness_risk: insufficient_context (confidence 0.300; detected probability 0.330)
- security_risk: insufficient_context (confidence 0.220; detected probability 0.240)
- maintainability_risk: detected (confidence 0.130; detected probability 0.420)
- no_major_issue: insufficient_context (confidence 0.060; detected probability 0.290)

## 13: backend/echolens/auth.py

Scope: file; status: reviewed.

- Lines 1–149 (backend/echolens/auth.py)
- runtime_error_risk: detected (confidence 0.310; detected probability 0.550)
- correctness_risk: not_detected (confidence 0.090; detected probability 0.380)
- security_risk: not_detected (confidence 0.210; detected probability 0.330)
- maintainability_risk: detected (confidence 0.350; detected probability 0.560)
- no_major_issue: detected (confidence 0.170; detected probability 0.450)

## 14: backend/echolens/backlog.py

Scope: file; status: reviewed.

- Lines 1–365 (backend/echolens/backlog.py)
- runtime_error_risk: detected (confidence 0.250; detected probability 0.500)
- correctness_risk: detected (confidence 0.490; detected probability 0.660)
- security_risk: not_detected (confidence 0.320; detected probability 0.030)
- maintainability_risk: detected (confidence 0.300; detected probability 0.530)
- no_major_issue: detected (confidence 0.080; detected probability 0.390)

## 15: backend/echolens/brain.py

Scope: file; status: reviewed.

- Lines 1–358 (backend/echolens/brain.py)
- runtime_error_risk: detected (confidence 0.370; detected probability 0.590)
- correctness_risk: detected (confidence 0.780; detected probability 0.850)
- security_risk: not_detected (confidence 0.210; detected probability 0.220)
- maintainability_risk: detected (confidence 0.760; detected probability 0.840)
- no_major_issue: detected (confidence 0.310; detected probability 0.540)

## 16: backend/echolens/brain.py

Scope: file; status: reviewed.

- Lines 359–405 (backend/echolens/brain.py)
- runtime_error_risk: insufficient_context (confidence 0.180; detected probability 0.250)
- correctness_risk: insufficient_context (confidence 0.500; detected probability 0.110)
- security_risk: not_detected (confidence 0.380; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.380; detected probability 0.070)
- no_major_issue: insufficient_context (confidence 0.170; detected probability 0.140)

## 17: backend/echolens/brief.py

Scope: file; status: reviewed.

- Lines 1–144 (backend/echolens/brief.py)
- runtime_error_risk: detected (confidence 0.190; detected probability 0.460)
- correctness_risk: detected (confidence 0.560; detected probability 0.700)
- security_risk: not_detected (confidence 0.320; detected probability 0.080)
- maintainability_risk: detected (confidence 0.310; detected probability 0.540)
- no_major_issue: insufficient_context (confidence 0.070; detected probability 0.300)

## 18: backend/echolens/calibration.py

Scope: file; status: reviewed.

- Lines 1–161 (backend/echolens/calibration.py)
- runtime_error_risk: not_detected (confidence 0.100; detected probability 0.390)
- correctness_risk: detected (confidence 0.170; detected probability 0.450)
- security_risk: not_detected (confidence 0.330; detected probability 0.070)
- maintainability_risk: detected (confidence 0.240; detected probability 0.490)
- no_major_issue: detected (confidence 0.190; detected probability 0.460)

## 19: backend/echolens/cases.py

Scope: file; status: reviewed.

- Lines 1–338 (backend/echolens/cases.py)
- runtime_error_risk: detected (confidence 0.360; detected probability 0.580)
- correctness_risk: detected (confidence 0.660; detected probability 0.770)
- security_risk: not_detected (confidence 0.490; detected probability 0.120)
- maintainability_risk: detected (confidence 0.370; detected probability 0.590)
- no_major_issue: not_detected (confidence 0.180; detected probability 0.400)

## 20: backend/echolens/cases.py

Scope: file; status: reviewed.

- Lines 339–467 (backend/echolens/cases.py)
- runtime_error_risk: detected (confidence 0.150; detected probability 0.440)
- correctness_risk: insufficient_context (confidence 0.290; detected probability 0.250)
- security_risk: not_detected (confidence 0.250; detected probability 0.100)
- maintainability_risk: not_detected (confidence 0.340; detected probability 0.250)
- no_major_issue: insufficient_context (confidence 0.020; detected probability 0.330)

## 21: backend/echolens/chat.py

Scope: file; status: reviewed.

- Lines 1–186 (backend/echolens/chat.py)
- runtime_error_risk: detected (confidence 0.410; detected probability 0.610)
- correctness_risk: detected (confidence 0.440; detected probability 0.630)
- security_risk: not_detected (confidence 0.200; detected probability 0.170)
- maintainability_risk: detected (confidence 0.550; detected probability 0.700)
- no_major_issue: detected (confidence 0.120; detected probability 0.420)

## 22: backend/echolens/cli.py

Scope: file; status: reviewed.

- Lines 1–303 (backend/echolens/cli.py)
- runtime_error_risk: detected (confidence 0.280; detected probability 0.510)
- correctness_risk: insufficient_context (confidence 0.630; detected probability 0.060)
- security_risk: insufficient_context (confidence 0.440; detected probability 0.190)
- maintainability_risk: detected (confidence 0.120; detected probability 0.410)
- no_major_issue: insufficient_context (confidence 0.160; detected probability 0.250)

## 23: backend/echolens/collab.py

Scope: file; status: reviewed.

- Lines 1–321 (backend/echolens/collab.py)
- runtime_error_risk: detected (confidence 0.340; detected probability 0.560)
- correctness_risk: not_detected (confidence 0.200; detected probability 0.400)
- security_risk: not_detected (confidence 0.460; detected probability 0.200)
- maintainability_risk: not_detected (confidence 0.310; detected probability 0.390)
- no_major_issue: not_detected (confidence 0.330; detected probability 0.320)

## 24: backend/echolens/collectors/app_store.py

Scope: file; status: reviewed.

- Lines 1–135 (backend/echolens/collectors/app_store.py)
- runtime_error_risk: detected (confidence 0.410; detected probability 0.610)
- correctness_risk: detected (confidence 0.240; detected probability 0.490)
- security_risk: not_detected (confidence 0.520; detected probability 0.080)
- maintainability_risk: not_detected (confidence 0.490; detected probability 0.250)
- no_major_issue: not_detected (confidence 0.360; detected probability 0.250)

## 25: backend/echolens/collectors/base.py

Scope: file; status: reviewed.

- Lines 1–172 (backend/echolens/collectors/base.py)
- runtime_error_risk: detected (confidence 0.100; detected probability 0.400)
- correctness_risk: not_detected (confidence 0.140; detected probability 0.330)
- security_risk: not_detected (confidence 0.640; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.370; detected probability 0.320)
- no_major_issue: not_detected (confidence 0.250; detected probability 0.240)

## 26: backend/echolens/collectors/chrome_web_store.py

Scope: file; status: reviewed.

- Lines 1–143 (backend/echolens/collectors/chrome_web_store.py)
- runtime_error_risk: detected (confidence 0.640; detected probability 0.760)
- correctness_risk: detected (confidence 0.720; detected probability 0.810)
- security_risk: not_detected (confidence 0.690; detected probability 0.030)
- maintainability_risk: detected (confidence 0.600; detected probability 0.740)
- no_major_issue: not_detected (confidence 0.220; detected probability 0.370)

## 27: backend/echolens/collectors/feedback_base.py

Scope: file; status: reviewed.

- Lines 1–111 (backend/echolens/collectors/feedback_base.py)
- runtime_error_risk: not_detected (confidence 0.150; detected probability 0.340)
- correctness_risk: not_detected (confidence 0.100; detected probability 0.290)
- security_risk: not_detected (confidence 0.600; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.550; detected probability 0.150)
- no_major_issue: not_detected (confidence 0.350; detected probability 0.220)

## 28: backend/echolens/collectors/github.py

Scope: file; status: reviewed.

- Lines 1–183 (backend/echolens/collectors/github.py)
- runtime_error_risk: detected (confidence 0.360; detected probability 0.570)
- correctness_risk: detected (confidence 0.520; detected probability 0.690)
- security_risk: not_detected (confidence 0.410; detected probability 0.160)
- maintainability_risk: not_detected (confidence 0.320; detected probability 0.400)
- no_major_issue: not_detected (confidence 0.290; detected probability 0.340)

## 29: backend/echolens/collectors/github_extra.py

Scope: file; status: reviewed.

- Lines 1–219 (backend/echolens/collectors/github_extra.py)
- runtime_error_risk: detected (confidence 0.520; detected probability 0.680)
- correctness_risk: detected (confidence 0.500; detected probability 0.660)
- security_risk: not_detected (confidence 0.520; detected probability 0.080)
- maintainability_risk: not_detected (confidence 0.290; detected probability 0.390)
- no_major_issue: not_detected (confidence 0.250; detected probability 0.340)

## 30: backend/echolens/collectors/hacker_news.py

Scope: file; status: reviewed.

- Lines 1–82 (backend/echolens/collectors/hacker_news.py)
- runtime_error_risk: detected (confidence 0.490; detected probability 0.650)
- correctness_risk: detected (confidence 0.500; detected probability 0.660)
- security_risk: not_detected (confidence 0.730; detected probability 0.020)
- maintainability_risk: detected (confidence 0.230; detected probability 0.490)
- no_major_issue: not_detected (confidence 0.210; detected probability 0.310)

## 31: backend/echolens/collectors/play_store.py

Scope: file; status: reviewed.

- Lines 1–117 (backend/echolens/collectors/play_store.py)
- runtime_error_risk: detected (confidence 0.380; detected probability 0.590)
- correctness_risk: detected (confidence 0.290; detected probability 0.520)
- security_risk: not_detected (confidence 0.720; detected probability 0.040)
- maintainability_risk: not_detected (confidence 0.270; detected probability 0.410)
- no_major_issue: not_detected (confidence 0.350; detected probability 0.340)

## 32: backend/echolens/collectors/registry.py

Scope: file; status: reviewed.

- Lines 1–270 (backend/echolens/collectors/registry.py)
- runtime_error_risk: detected (confidence 0.280; detected probability 0.520)
- correctness_risk: detected (confidence 0.160; detected probability 0.440)
- security_risk: not_detected (confidence 0.460; detected probability 0.040)
- maintainability_risk: not_detected (confidence 0.230; detected probability 0.430)
- no_major_issue: not_detected (confidence 0.190; detected probability 0.300)

## 33: backend/echolens/collectors/scheduler.py

Scope: file; status: reviewed.

- Lines 1–65 (backend/echolens/collectors/scheduler.py)
- runtime_error_risk: detected (confidence 0.240; detected probability 0.500)
- correctness_risk: detected (confidence 0.280; detected probability 0.530)
- security_risk: not_detected (confidence 0.210; detected probability 0.080)
- maintainability_risk: detected (confidence 0.270; detected probability 0.520)
- no_major_issue: insufficient_context (confidence 0.020; detected probability 0.330)

## 34: backend/echolens/collectors/stack_overflow.py

Scope: file; status: reviewed.

- Lines 1–89 (backend/echolens/collectors/stack_overflow.py)
- runtime_error_risk: detected (confidence 0.510; detected probability 0.670)
- correctness_risk: detected (confidence 0.270; detected probability 0.510)
- security_risk: not_detected (confidence 0.780; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.350; detected probability 0.300)
- no_major_issue: not_detected (confidence 0.280; detected probability 0.280)

## 35: backend/echolens/config.py

Scope: file; status: reviewed.

- Lines 1–221 (backend/echolens/config.py)
- runtime_error_risk: detected (confidence 0.140; detected probability 0.430)
- correctness_risk: not_detected (confidence 0.130; detected probability 0.170)
- security_risk: insufficient_context (confidence 0.240; detected probability 0.180)
- maintainability_risk: not_detected (confidence 0.200; detected probability 0.430)
- no_major_issue: detected (confidence 0.170; detected probability 0.440)

## 36: backend/echolens/db/migrate.py

Scope: file; status: reviewed.

- Lines 1–122 (backend/echolens/db/migrate.py)
- runtime_error_risk: detected (confidence 0.380; detected probability 0.590)
- correctness_risk: detected (confidence 0.280; detected probability 0.520)
- security_risk: not_detected (confidence 0.440; detected probability 0.090)
- maintainability_risk: detected (confidence 0.380; detected probability 0.580)
- no_major_issue: detected (confidence 0.050; detected probability 0.370)

## 37: backend/echolens/db/models.py

Scope: file; status: reviewed.

- Lines 1–341 (backend/echolens/db/models.py)
- runtime_error_risk: not_detected (confidence 0.200; detected probability 0.220)
- correctness_risk: insufficient_context (confidence 0.500; detected probability 0.040)
- security_risk: insufficient_context (confidence 0.400; detected probability 0.050)
- maintainability_risk: not_detected (confidence 0.300; detected probability 0.310)
- no_major_issue: insufficient_context (confidence 0.130; detected probability 0.180)

## 38: backend/echolens/db/models.py

Scope: file; status: reviewed.

- Lines 342–492 (backend/echolens/db/models.py)
- runtime_error_risk: not_detected (confidence 0.210; detected probability 0.140)
- correctness_risk: insufficient_context (confidence 0.480; detected probability 0.020)
- security_risk: insufficient_context (confidence 0.410; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.420; detected probability 0.180)
- no_major_issue: not_detected (confidence 0.230; detected probability 0.130)

## 39: backend/echolens/db/session.py

Scope: file; status: reviewed.

- Lines 1–171 (backend/echolens/db/session.py)
- runtime_error_risk: detected (confidence 0.490; detected probability 0.660)
- correctness_risk: insufficient_context (confidence 0.170; detected probability 0.280)
- security_risk: not_detected (confidence 0.110; detected probability 0.360)
- maintainability_risk: detected (confidence 0.460; detected probability 0.640)
- no_major_issue: not_detected (confidence 0.170; detected probability 0.350)

## 40: backend/echolens/detector/detect.py

Scope: file; status: reviewed.

- Lines 1–343 (backend/echolens/detector/detect.py)
- runtime_error_risk: not_detected (confidence 0.110; detected probability 0.380)
- correctness_risk: detected (confidence 0.270; detected probability 0.510)
- security_risk: not_detected (confidence 0.660; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.440; detected probability 0.260)
- no_major_issue: not_detected (confidence 0.220; detected probability 0.280)

## 41: backend/echolens/detector/detect.py

Scope: file; status: reviewed.

- Lines 344–533 (backend/echolens/detector/detect.py)
- runtime_error_risk: insufficient_context (confidence 0.050; detected probability 0.320)
- correctness_risk: detected (confidence 0.430; detected probability 0.620)
- security_risk: not_detected (confidence 0.440; detected probability 0.060)
- maintainability_risk: detected (confidence 0.390; detected probability 0.600)
- no_major_issue: not_detected (confidence 0.030; detected probability 0.320)

## 42: backend/echolens/eval/__init__.py

Scope: file; status: reviewed.

- Lines 1–3 (backend/echolens/eval/__init__.py)
- runtime_error_risk: insufficient_context (confidence 0.550; detected probability 0.040)
- correctness_risk: insufficient_context (confidence 0.780; detected probability 0.000)
- security_risk: insufficient_context (confidence 0.330; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.280; detected probability 0.000)
- no_major_issue: insufficient_context (confidence 0.450; detected probability 0.040)

## 43: backend/echolens/eval/harness.py

Scope: file; status: reviewed.

- Lines 1–283 (backend/echolens/eval/harness.py)
- runtime_error_risk: detected (confidence 0.530; detected probability 0.680)
- correctness_risk: insufficient_context (confidence 0.480; detected probability 0.250)
- security_risk: not_detected (confidence 0.350; detected probability 0.030)
- maintainability_risk: detected (confidence 0.190; detected probability 0.460)
- no_major_issue: insufficient_context (confidence 0.320; detected probability 0.180)

## 44: backend/echolens/eval/harness.py

Scope: file; status: reviewed.

- Lines 284–359 (backend/echolens/eval/harness.py)
- runtime_error_risk: insufficient_context (confidence 0.160; detected probability 0.410)
- correctness_risk: insufficient_context (confidence 0.340; detected probability 0.250)
- security_risk: not_detected (confidence 0.360; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.290; detected probability 0.210)
- no_major_issue: insufficient_context (confidence 0.360; detected probability 0.170)

## 45: backend/echolens/exporting.py

Scope: file; status: reviewed.

- Lines 1–78 (backend/echolens/exporting.py)
- runtime_error_risk: detected (confidence 0.620; detected probability 0.740)
- correctness_risk: insufficient_context (confidence 0.140; detected probability 0.270)
- security_risk: not_detected (confidence 0.130; detected probability 0.260)
- maintainability_risk: detected (confidence 0.220; detected probability 0.470)
- no_major_issue: detected (confidence 0.060; detected probability 0.380)

## 46: backend/echolens/feedback.py

Scope: file; status: reviewed.

- Lines 1–371 (backend/echolens/feedback.py)
- runtime_error_risk: detected (confidence 0.620; detected probability 0.740)
- correctness_risk: detected (confidence 0.910; detected probability 0.940)
- security_risk: not_detected (confidence 0.380; detected probability 0.060)
- maintainability_risk: detected (confidence 0.810; detected probability 0.880)
- no_major_issue: detected (confidence 0.390; detected probability 0.590)

## 47: backend/echolens/feedback_graph.py

Scope: file; status: reviewed.

- Lines 1–182 (backend/echolens/feedback_graph.py)
- runtime_error_risk: insufficient_context (confidence 0.170; detected probability 0.410)
- correctness_risk: insufficient_context (confidence 0.210; detected probability 0.350)
- security_risk: insufficient_context (confidence 0.300; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.130; detected probability 0.380)
- no_major_issue: insufficient_context (confidence 0.400; detected probability 0.130)

## 48: backend/echolens/fixwatch.py

Scope: file; status: reviewed.

- Lines 1–319 (backend/echolens/fixwatch.py)
- runtime_error_risk: detected (confidence 0.480; detected probability 0.650)
- correctness_risk: detected (confidence 0.520; detected probability 0.680)
- security_risk: not_detected (confidence 0.510; detected probability 0.030)
- maintainability_risk: detected (confidence 0.270; detected probability 0.520)
- no_major_issue: not_detected (confidence 0.100; detected probability 0.340)

## 49: backend/echolens/google_auth.py

Scope: file; status: reviewed.

- Lines 1–143 (backend/echolens/google_auth.py)
- runtime_error_risk: detected (confidence 0.410; detected probability 0.610)
- correctness_risk: not_detected (confidence 0.400; detected probability 0.220)
- security_risk: not_detected (confidence 0.560; detected probability 0.200)
- maintainability_risk: not_detected (confidence 0.370; detected probability 0.380)
- no_major_issue: not_detected (confidence 0.330; detected probability 0.370)

## 50: backend/echolens/impact.py

Scope: file; status: reviewed.

- Lines 1–240 (backend/echolens/impact.py)
- runtime_error_risk: detected (confidence 0.340; detected probability 0.560)
- correctness_risk: detected (confidence 0.560; detected probability 0.710)
- security_risk: not_detected (confidence 0.170; detected probability 0.220)
- maintainability_risk: detected (confidence 0.410; detected probability 0.600)
- no_major_issue: detected (confidence 0.180; detected probability 0.450)

## 51: backend/echolens/importers/__init__.py

Scope: file; status: reviewed.

- Lines 1–2 (backend/echolens/importers/__init__.py)
- runtime_error_risk: insufficient_context (confidence 0.500; detected probability 0.000)
- correctness_risk: insufficient_context (confidence 0.930; detected probability 0.000)
- security_risk: insufficient_context (confidence 0.770; detected probability 0.000)
- maintainability_risk: insufficient_context (confidence 0.700; detected probability 0.000)
- no_major_issue: insufficient_context (confidence 0.780; detected probability 0.010)

## 52: backend/echolens/importers/csv_reviews.py

Scope: file; status: reviewed.

- Lines 1–130 (backend/echolens/importers/csv_reviews.py)
- runtime_error_risk: detected (confidence 0.280; detected probability 0.520)
- correctness_risk: detected (confidence 0.310; detected probability 0.540)
- security_risk: not_detected (confidence 0.560; detected probability 0.070)
- maintainability_risk: not_detected (confidence 0.340; detected probability 0.330)
- no_major_issue: not_detected (confidence 0.330; detected probability 0.310)

## 53: backend/echolens/importers/feedback_csv.py

Scope: file; status: reviewed.

- Lines 1–129 (backend/echolens/importers/feedback_csv.py)
- runtime_error_risk: detected (confidence 0.480; detected probability 0.650)
- correctness_risk: detected (confidence 0.520; detected probability 0.680)
- security_risk: not_detected (confidence 0.310; detected probability 0.200)
- maintainability_risk: detected (confidence 0.300; detected probability 0.530)
- no_major_issue: not_detected (confidence 0.140; detected probability 0.420)

## 54: backend/echolens/importers/spreadsheet.py

Scope: file; status: reviewed.

- Lines 1–82 (backend/echolens/importers/spreadsheet.py)
- runtime_error_risk: detected (confidence 0.380; detected probability 0.580)
- correctness_risk: not_detected (confidence 0.140; detected probability 0.230)
- security_risk: not_detected (confidence 0.720; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.590; detected probability 0.130)
- no_major_issue: not_detected (confidence 0.340; detected probability 0.230)

## 55: backend/echolens/integrations/__init__.py

Scope: file; status: reviewed.

- Lines 1–2 (backend/echolens/integrations/__init__.py)
- runtime_error_risk: insufficient_context (confidence 0.470; detected probability 0.000)
- correctness_risk: insufficient_context (confidence 0.930; detected probability 0.000)
- security_risk: insufficient_context (confidence 0.810; detected probability 0.000)
- maintainability_risk: insufficient_context (confidence 0.640; detected probability 0.000)
- no_major_issue: insufficient_context (confidence 0.850; detected probability 0.010)

## 56: backend/echolens/integrations/github_issue.py

Scope: file; status: reviewed.

- Lines 1–38 (backend/echolens/integrations/github_issue.py)
- runtime_error_risk: detected (confidence 0.270; detected probability 0.510)
- correctness_risk: not_detected (confidence 0.470; detected probability 0.110)
- security_risk: not_detected (confidence 0.420; detected probability 0.160)
- maintainability_risk: not_detected (confidence 0.700; detected probability 0.120)
- no_major_issue: not_detected (confidence 0.460; detected probability 0.230)

## 57: backend/echolens/investigator/graph.py

Scope: file; status: reviewed.

- Lines 1–377 (backend/echolens/investigator/graph.py)
- runtime_error_risk: detected (confidence 0.270; detected probability 0.510)
- correctness_risk: insufficient_context (confidence 0.400; detected probability 0.370)
- security_risk: insufficient_context (confidence 0.220; detected probability 0.060)
- maintainability_risk: detected (confidence 0.410; detected probability 0.600)
- no_major_issue: insufficient_context (confidence 0.190; detected probability 0.380)

## 58: backend/echolens/investigator/graph.py

Scope: file; status: reviewed.

- Lines 378–704 (backend/echolens/investigator/graph.py)
- runtime_error_risk: detected (confidence 0.470; detected probability 0.650)
- correctness_risk: detected (confidence 0.250; detected probability 0.500)
- security_risk: insufficient_context (confidence 0.360; detected probability 0.040)
- maintainability_risk: detected (confidence 0.700; detected probability 0.800)
- no_major_issue: detected (confidence 0.330; detected probability 0.560)

## 59: backend/echolens/investigator/graph.py

Scope: file; status: reviewed.

- Lines 705–912 (backend/echolens/investigator/graph.py)
- runtime_error_risk: detected (confidence 0.270; detected probability 0.510)
- correctness_risk: detected (confidence 0.400; detected probability 0.590)
- security_risk: insufficient_context (confidence 0.210; detected probability 0.230)
- maintainability_risk: detected (confidence 0.520; detected probability 0.680)
- no_major_issue: detected (confidence 0.390; detected probability 0.590)

## 60: backend/echolens/investigator/guards.py

Scope: file; status: reviewed.

- Lines 1–197 (backend/echolens/investigator/guards.py)
- runtime_error_risk: not_detected (confidence 0.220; detected probability 0.320)
- correctness_risk: detected (confidence 0.190; detected probability 0.450)
- security_risk: not_detected (confidence 0.700; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.220; detected probability 0.440)
- no_major_issue: not_detected (confidence 0.190; detected probability 0.290)

## 61: backend/echolens/investigator/memory.py

Scope: file; status: reviewed.

- Lines 1–69 (backend/echolens/investigator/memory.py)
- runtime_error_risk: detected (confidence 0.380; detected probability 0.590)
- correctness_risk: detected (confidence 0.050; detected probability 0.360)
- security_risk: not_detected (confidence 0.310; detected probability 0.180)
- maintainability_risk: not_detected (confidence 0.210; detected probability 0.330)
- no_major_issue: not_detected (confidence 0.150; detected probability 0.240)

## 62: backend/echolens/investigator/prompts.py

Scope: file; status: reviewed.

- Lines 1–209 (backend/echolens/investigator/prompts.py)
- runtime_error_risk: not_detected (confidence 0.130; detected probability 0.160)
- correctness_risk: insufficient_context (confidence 0.550; detected probability 0.010)
- security_risk: not_detected (confidence 0.510; detected probability 0.030)
- maintainability_risk: not_detected (confidence 0.480; detected probability 0.110)
- no_major_issue: insufficient_context (confidence 0.190; detected probability 0.090)

## 63: backend/echolens/investigator/recover.py

Scope: file; status: reviewed.

- Lines 1–54 (backend/echolens/investigator/recover.py)
- runtime_error_risk: insufficient_context (confidence 0.180; detected probability 0.260)
- correctness_risk: insufficient_context (confidence 0.160; detected probability 0.160)
- security_risk: not_detected (confidence 0.460; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.250; detected probability 0.240)
- no_major_issue: not_detected (confidence 0.120; detected probability 0.210)

## 64: backend/echolens/investigator/specialists.py

Scope: file; status: reviewed.

- Lines 1–80 (backend/echolens/investigator/specialists.py)
- runtime_error_risk: not_detected (confidence 0.150; detected probability 0.270)
- correctness_risk: insufficient_context (confidence 0.450; detected probability 0.120)
- security_risk: not_detected (confidence 0.550; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.590; detected probability 0.080)
- no_major_issue: not_detected (confidence 0.320; detected probability 0.090)

## 65: backend/echolens/investigator/state.py

Scope: file; status: reviewed.

- Lines 1–60 (backend/echolens/investigator/state.py)
- runtime_error_risk: insufficient_context (confidence 0.080; detected probability 0.340)
- correctness_risk: insufficient_context (confidence 0.360; detected probability 0.130)
- security_risk: not_detected (confidence 0.380; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.290; detected probability 0.200)
- no_major_issue: not_detected (confidence 0.170; detected probability 0.120)

## 66: backend/echolens/llm/client.py

Scope: file; status: reviewed.

- Lines 1–131 (backend/echolens/llm/client.py)
- runtime_error_risk: not_detected (confidence 0.350; detected probability 0.340)
- correctness_risk: detected (confidence 0.540; detected probability 0.700)
- security_risk: not_detected (confidence 0.790; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.300; detected probability 0.350)
- no_major_issue: not_detected (confidence 0.370; detected probability 0.300)

## 67: backend/echolens/llm/openai_client.py

Scope: file; status: reviewed.

- Lines 1–167 (backend/echolens/llm/openai_client.py)
- runtime_error_risk: detected (confidence 0.490; detected probability 0.660)
- correctness_risk: detected (confidence 0.210; detected probability 0.470)
- security_risk: not_detected (confidence 0.530; detected probability 0.050)
- maintainability_risk: detected (confidence 0.250; detected probability 0.500)
- no_major_issue: not_detected (confidence 0.350; detected probability 0.320)

## 68: backend/echolens/logging.py

Scope: file; status: reviewed.

- Lines 1–85 (backend/echolens/logging.py)
- runtime_error_risk: not_detected (confidence 0.310; detected probability 0.350)
- correctness_risk: not_detected (confidence 0.480; detected probability 0.070)
- security_risk: not_detected (confidence 0.840; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.470; detected probability 0.240)
- no_major_issue: not_detected (confidence 0.390; detected probability 0.260)

## 69: backend/echolens/notify.py

Scope: file; status: reviewed.

- Lines 1–141 (backend/echolens/notify.py)
- runtime_error_risk: detected (confidence 0.520; detected probability 0.680)
- correctness_risk: insufficient_context (confidence 0.150; detected probability 0.200)
- security_risk: not_detected (confidence 0.300; detected probability 0.180)
- maintainability_risk: not_detected (confidence 0.250; detected probability 0.340)
- no_major_issue: not_detected (confidence 0.040; detected probability 0.330)

## 70: backend/echolens/onboarding/__init__.py

Scope: file; status: reviewed.

- Lines 1–3 (backend/echolens/onboarding/__init__.py)
- runtime_error_risk: insufficient_context (confidence 0.690; detected probability 0.000)
- correctness_risk: insufficient_context (confidence 0.960; detected probability 0.000)
- security_risk: insufficient_context (confidence 0.880; detected probability 0.000)
- maintainability_risk: insufficient_context (confidence 0.800; detected probability 0.000)
- no_major_issue: insufficient_context (confidence 0.940; detected probability 0.000)

## 71: backend/echolens/onboarding/snapshot.py

Scope: file; status: reviewed.

- Lines 1–92 (backend/echolens/onboarding/snapshot.py)
- runtime_error_risk: detected (confidence 0.070; detected probability 0.380)
- correctness_risk: detected (confidence 0.210; detected probability 0.470)
- security_risk: not_detected (confidence 0.320; detected probability 0.070)
- maintainability_risk: not_detected (confidence 0.260; detected probability 0.360)
- no_major_issue: not_detected (confidence 0.230; detected probability 0.200)

## 72: backend/echolens/onboarding/validate.py

Scope: file; status: reviewed.

- Lines 1–40 (backend/echolens/onboarding/validate.py)
- runtime_error_risk: not_detected (confidence 0.660; detected probability 0.200)
- correctness_risk: not_detected (confidence 0.530; detected probability 0.140)
- security_risk: not_detected (confidence 0.940; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.710; detected probability 0.120)
- no_major_issue: not_detected (confidence 0.470; detected probability 0.290)

## 73: backend/echolens/orchestrator/queue.py

Scope: file; status: reviewed.

- Lines 1–313 (backend/echolens/orchestrator/queue.py)
- runtime_error_risk: detected (confidence 0.190; detected probability 0.460)
- correctness_risk: detected (confidence 0.230; detected probability 0.490)
- security_risk: not_detected (confidence 0.490; detected probability 0.070)
- maintainability_risk: not_detected (confidence 0.300; detected probability 0.370)
- no_major_issue: not_detected (confidence 0.260; detected probability 0.260)

## 74: backend/echolens/orchestrator/triage.py

Scope: file; status: reviewed.

- Lines 1–261 (backend/echolens/orchestrator/triage.py)
- runtime_error_risk: detected (confidence 0.370; detected probability 0.580)
- correctness_risk: detected (confidence 0.500; detected probability 0.670)
- security_risk: not_detected (confidence 0.290; detected probability 0.180)
- maintainability_risk: detected (confidence 0.630; detected probability 0.760)
- no_major_issue: detected (confidence 0.190; detected probability 0.460)

## 75: backend/echolens/patterns.py

Scope: file; status: reviewed.

- Lines 1–126 (backend/echolens/patterns.py)
- runtime_error_risk: detected (confidence 0.090; detected probability 0.390)
- correctness_risk: insufficient_context (confidence 0.030; detected probability 0.340)
- security_risk: not_detected (confidence 0.460; detected probability 0.090)
- maintainability_risk: detected (confidence 0.190; detected probability 0.460)
- no_major_issue: not_detected (confidence 0.130; detected probability 0.250)

## 76: backend/echolens/portfolio.py

Scope: file; status: reviewed.

- Lines 1–352 (backend/echolens/portfolio.py)
- runtime_error_risk: detected (confidence 0.210; detected probability 0.480)
- correctness_risk: detected (confidence 0.460; detected probability 0.640)
- security_risk: not_detected (confidence 0.270; detected probability 0.090)
- maintainability_risk: detected (confidence 0.220; detected probability 0.480)
- no_major_issue: not_detected (confidence 0.080; detected probability 0.250)

## 77: backend/echolens/recommender/recommend.py

Scope: file; status: reviewed.

- Lines 1–99 (backend/echolens/recommender/recommend.py)
- runtime_error_risk: detected (confidence 0.420; detected probability 0.610)
- correctness_risk: detected (confidence 0.210; detected probability 0.470)
- security_risk: not_detected (confidence 0.400; detected probability 0.080)
- maintainability_risk: detected (confidence 0.530; detected probability 0.690)
- no_major_issue: not_detected (confidence 0.090; detected probability 0.370)

## 78: backend/echolens/review.py

Scope: file; status: reviewed.

- Lines 1–81 (backend/echolens/review.py)
- runtime_error_risk: detected (confidence 0.660; detected probability 0.770)
- correctness_risk: detected (confidence 0.100; detected probability 0.400)
- security_risk: insufficient_context (confidence 0.210; detected probability 0.160)
- maintainability_risk: detected (confidence 0.340; detected probability 0.550)
- no_major_issue: detected (confidence 0.180; detected probability 0.450)

## 79: backend/echolens/search/embedder.py

Scope: file; status: reviewed.

- Lines 1–87 (backend/echolens/search/embedder.py)
- runtime_error_risk: not_detected (confidence 0.130; detected probability 0.320)
- correctness_risk: not_detected (confidence 0.370; detected probability 0.150)
- security_risk: not_detected (confidence 0.890; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.390; detected probability 0.300)
- no_major_issue: not_detected (confidence 0.400; detected probability 0.250)

## 80: backend/echolens/search/semantic.py

Scope: file; status: reviewed.

- Lines 1–78 (backend/echolens/search/semantic.py)
- runtime_error_risk: detected (confidence 0.140; detected probability 0.430)
- correctness_risk: not_detected (confidence 0.190; detected probability 0.150)
- security_risk: not_detected (confidence 0.480; detected probability 0.100)
- maintainability_risk: not_detected (confidence 0.440; detected probability 0.160)
- no_major_issue: not_detected (confidence 0.210; detected probability 0.170)

## 81: backend/echolens/synthetic/generate.py

Scope: file; status: reviewed.

- Lines 1–225 (backend/echolens/synthetic/generate.py)
- runtime_error_risk: not_detected (confidence 0.200; detected probability 0.130)
- correctness_risk: not_detected (confidence 0.170; detected probability 0.210)
- security_risk: not_detected (confidence 0.570; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.310; detected probability 0.340)
- no_major_issue: not_detected (confidence 0.120; detected probability 0.210)

## 82: backend/echolens/textkit.py

Scope: file; status: reviewed.

- Lines 1–89 (backend/echolens/textkit.py)
- runtime_error_risk: not_detected (confidence 0.800; detected probability 0.100)
- correctness_risk: not_detected (confidence 0.150; detected probability 0.320)
- security_risk: not_detected (confidence 0.900; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.530; detected probability 0.230)
- no_major_issue: not_detected (confidence 0.540; detected probability 0.220)

## 83: backend/echolens/themes/__init__.py

Scope: file; status: reviewed.

- Lines 1–71 (backend/echolens/themes/__init__.py)
- runtime_error_risk: detected (confidence 0.090; detected probability 0.390)
- correctness_risk: detected (confidence 0.290; detected probability 0.520)
- security_risk: not_detected (confidence 0.510; detected probability 0.050)
- maintainability_risk: not_detected (confidence 0.180; detected probability 0.330)
- no_major_issue: not_detected (confidence 0.150; detected probability 0.230)

## 84: backend/echolens/themes/discover.py

Scope: file; status: reviewed.

- Lines 1–400 (backend/echolens/themes/discover.py)
- runtime_error_risk: detected (confidence 0.220; detected probability 0.480)
- correctness_risk: detected (confidence 0.170; detected probability 0.450)
- security_risk: not_detected (confidence 0.690; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.300; detected probability 0.330)
- no_major_issue: not_detected (confidence 0.180; detected probability 0.180)

## 85: backend/echolens/themes/discover.py

Scope: file; status: reviewed.

- Lines 401–610 (backend/echolens/themes/discover.py)
- runtime_error_risk: detected (confidence 0.390; detected probability 0.590)
- correctness_risk: detected (confidence 0.500; detected probability 0.660)
- security_risk: not_detected (confidence 0.290; detected probability 0.040)
- maintainability_risk: detected (confidence 0.410; detected probability 0.600)
- no_major_issue: not_detected (confidence 0.070; detected probability 0.280)

## 86: backend/echolens/timeutil.py

Scope: file; status: reviewed.

- Lines 1–12 (backend/echolens/timeutil.py)
- runtime_error_risk: not_detected (confidence 0.850; detected probability 0.020)
- correctness_risk: not_detected (confidence 0.480; detected probability 0.010)
- security_risk: not_detected (confidence 0.880; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.780; detected probability 0.010)
- no_major_issue: not_detected (confidence 0.660; detected probability 0.100)

## 87: backend/echolens/tools/_util.py

Scope: file; status: reviewed.

- Lines 1–51 (backend/echolens/tools/_util.py)
- runtime_error_risk: not_detected (confidence 0.210; detected probability 0.390)
- correctness_risk: not_detected (confidence 0.340; detected probability 0.260)
- security_risk: not_detected (confidence 0.740; detected probability 0.070)
- maintainability_risk: not_detected (confidence 0.640; detected probability 0.120)
- no_major_issue: not_detected (confidence 0.400; detected probability 0.280)

## 88: backend/echolens/tools/analyze_trend.py

Scope: file; status: reviewed.

- Lines 1–94 (backend/echolens/tools/analyze_trend.py)
- runtime_error_risk: detected (confidence 0.330; detected probability 0.550)
- correctness_risk: detected (confidence 0.780; detected probability 0.850)
- security_risk: not_detected (confidence 0.630; detected probability 0.030)
- maintainability_risk: detected (confidence 0.460; detected probability 0.640)
- no_major_issue: detected (confidence 0.270; detected probability 0.520)

## 89: backend/echolens/tools/compare_cohorts.py

Scope: file; status: reviewed.

- Lines 1–93 (backend/echolens/tools/compare_cohorts.py)
- runtime_error_risk: detected (confidence 0.300; detected probability 0.540)
- correctness_risk: detected (confidence 0.240; detected probability 0.500)
- security_risk: not_detected (confidence 0.610; detected probability 0.040)
- maintainability_risk: not_detected (confidence 0.340; detected probability 0.250)
- no_major_issue: not_detected (confidence 0.220; detected probability 0.230)

## 90: backend/echolens/tools/compare_periods.py

Scope: file; status: reviewed.

- Lines 1–71 (backend/echolens/tools/compare_periods.py)
- runtime_error_risk: detected (confidence 0.410; detected probability 0.610)
- correctness_risk: detected (confidence 0.340; detected probability 0.560)
- security_risk: not_detected (confidence 0.520; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.300; detected probability 0.330)
- no_major_issue: not_detected (confidence 0.190; detected probability 0.290)

## 91: backend/echolens/tools/get_release_notes.py

Scope: file; status: reviewed.

- Lines 1–45 (backend/echolens/tools/get_release_notes.py)
- runtime_error_risk: insufficient_context (confidence 0.120; detected probability 0.230)
- correctness_risk: not_detected (confidence 0.110; detected probability 0.220)
- security_risk: not_detected (confidence 0.480; detected probability 0.110)
- maintainability_risk: not_detected (confidence 0.510; detected probability 0.200)
- no_major_issue: not_detected (confidence 0.280; detected probability 0.240)

## 92: backend/echolens/tools/registry.py

Scope: file; status: reviewed.

- Lines 1–231 (backend/echolens/tools/registry.py)
- runtime_error_risk: detected (confidence 0.090; detected probability 0.390)
- correctness_risk: insufficient_context (confidence 0.140; detected probability 0.300)
- security_risk: not_detected (confidence 0.420; detected probability 0.040)
- maintainability_risk: not_detected (confidence 0.510; detected probability 0.270)
- no_major_issue: not_detected (confidence 0.350; detected probability 0.200)

## 93: backend/echolens/tools/review_stats.py

Scope: file; status: reviewed.

- Lines 1–65 (backend/echolens/tools/review_stats.py)
- runtime_error_risk: detected (confidence 0.090; detected probability 0.390)
- correctness_risk: detected (confidence 0.050; detected probability 0.370)
- security_risk: not_detected (confidence 0.600; detected probability 0.060)
- maintainability_risk: not_detected (confidence 0.430; detected probability 0.210)
- no_major_issue: not_detected (confidence 0.280; detected probability 0.180)

## 94: backend/echolens/tools/search_github_issues.py

Scope: file; status: reviewed.

- Lines 1–51 (backend/echolens/tools/search_github_issues.py)
- runtime_error_risk: insufficient_context (confidence 0.390; detected probability 0.260)
- correctness_risk: insufficient_context (confidence 0.500; detected probability 0.190)
- security_risk: insufficient_context (confidence 0.300; detected probability 0.130)
- maintainability_risk: not_detected (confidence 0.080; detected probability 0.270)
- no_major_issue: insufficient_context (confidence 0.410; detected probability 0.120)

## 95: backend/echolens/tools/search_reddit.py

Scope: file; status: reviewed.

- Lines 1–49 (backend/echolens/tools/search_reddit.py)
- runtime_error_risk: insufficient_context (confidence 0.470; detected probability 0.240)
- correctness_risk: insufficient_context (confidence 0.530; detected probability 0.180)
- security_risk: insufficient_context (confidence 0.380; detected probability 0.110)
- maintainability_risk: insufficient_context (confidence 0.070; detected probability 0.250)
- no_major_issue: insufficient_context (confidence 0.480; detected probability 0.100)

## 96: backend/echolens/tools/search_reviews.py

Scope: file; status: reviewed.

- Lines 1–68 (backend/echolens/tools/search_reviews.py)
- runtime_error_risk: insufficient_context (confidence 0.300; detected probability 0.320)
- correctness_risk: insufficient_context (confidence 0.300; detected probability 0.290)
- security_risk: not_detected (confidence 0.080; detected probability 0.260)
- maintainability_risk: not_detected (confidence 0.100; detected probability 0.330)
- no_major_issue: insufficient_context (confidence 0.250; detected probability 0.180)

## 97: backend/echolens/vocab.py

Scope: file; status: reviewed.

- Lines 1–167 (backend/echolens/vocab.py)
- runtime_error_risk: detected (confidence 0.080; detected probability 0.390)
- correctness_risk: detected (confidence 0.360; detected probability 0.580)
- security_risk: not_detected (confidence 0.650; detected probability 0.020)
- maintainability_risk: detected (confidence 0.220; detected probability 0.480)
- no_major_issue: not_detected (confidence 0.130; detected probability 0.290)

## 98: backend/pyproject.toml

Scope: file; status: reviewed.

- Lines 1–44 (backend/pyproject.toml)
- runtime_error_risk: insufficient_context (confidence 0.270; detected probability 0.010)
- correctness_risk: insufficient_context (confidence 0.660; detected probability 0.000)
- security_risk: insufficient_context (confidence 0.730; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.290; detected probability 0.040)
- no_major_issue: insufficient_context (confidence 0.460; detected probability 0.030)

## 99: backend/tests/conftest.py

Scope: file; status: reviewed.

- Lines 1–48 (backend/tests/conftest.py)
- runtime_error_risk: not_detected (confidence 0.480; detected probability 0.120)
- correctness_risk: not_detected (confidence 0.510; detected probability 0.020)
- security_risk: not_detected (confidence 0.760; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.620; detected probability 0.100)
- no_major_issue: not_detected (confidence 0.460; detected probability 0.120)

## 100: backend/tests/test_adaptive_budget.py

Scope: file; status: reviewed.

- Lines 1–36 (backend/tests/test_adaptive_budget.py)
- runtime_error_risk: insufficient_context (confidence 0.470; detected probability 0.040)
- correctness_risk: insufficient_context (confidence 0.690; detected probability 0.000)
- security_risk: not_detected (confidence 0.530; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.460; detected probability 0.030)
- no_major_issue: insufficient_context (confidence 0.350; detected probability 0.050)

## 101: backend/tests/test_api.py

Scope: file; status: reviewed.

- Lines 1–60 (backend/tests/test_api.py)
- runtime_error_risk: detected (confidence 0.450; detected probability 0.630)
- correctness_risk: insufficient_context (confidence 0.400; detected probability 0.310)
- security_risk: insufficient_context (confidence 0.670; detected probability 0.050)
- maintainability_risk: detected (confidence 0.460; detected probability 0.640)
- no_major_issue: insufficient_context (confidence 0.080; detected probability 0.340)

## 102: backend/tests/test_ask_agent.py

Scope: file; status: reviewed.

- Lines 1–141 (backend/tests/test_ask_agent.py)
- runtime_error_risk: not_detected (confidence 0.320; detected probability 0.110)
- correctness_risk: insufficient_context (confidence 0.330; detected probability 0.040)
- security_risk: not_detected (confidence 0.530; detected probability 0.040)
- maintainability_risk: not_detected (confidence 0.600; detected probability 0.050)
- no_major_issue: not_detected (confidence 0.320; detected probability 0.110)

## 103: backend/tests/test_audit.py

Scope: file; status: reviewed.

- Lines 1–188 (backend/tests/test_audit.py)
- runtime_error_risk: not_detected (confidence 0.240; detected probability 0.200)
- correctness_risk: insufficient_context (confidence 0.450; detected probability 0.040)
- security_risk: insufficient_context (confidence 0.340; detected probability 0.030)
- maintainability_risk: not_detected (confidence 0.450; detected probability 0.110)
- no_major_issue: insufficient_context (confidence 0.160; detected probability 0.120)

## 104: backend/tests/test_audit_2026_07_27.py

Scope: file; status: reviewed.

- Lines 1–412 (backend/tests/test_audit_2026_07_27.py)
- runtime_error_risk: detected (confidence 0.110; detected probability 0.410)
- correctness_risk: insufficient_context (confidence 0.190; detected probability 0.260)
- security_risk: insufficient_context (confidence 0.280; detected probability 0.060)
- maintainability_risk: detected (confidence 0.420; detected probability 0.610)
- no_major_issue: detected (confidence 0.070; detected probability 0.390)

## 105: backend/tests/test_audit_2026_07_27.py

Scope: file; status: reviewed.

- Lines 413–525 (backend/tests/test_audit_2026_07_27.py)
- runtime_error_risk: insufficient_context (confidence 0.310; detected probability 0.270)
- correctness_risk: insufficient_context (confidence 0.450; detected probability 0.220)
- security_risk: not_detected (confidence 0.270; detected probability 0.010)
- maintainability_risk: insufficient_context (confidence 0.120; detected probability 0.340)
- no_major_issue: insufficient_context (confidence 0.270; detected probability 0.160)

## 106: backend/tests/test_audit_2026_08_02.py

Scope: file; status: reviewed.

- Lines 1–259 (backend/tests/test_audit_2026_08_02.py)
- runtime_error_risk: not_detected (confidence 0.230; detected probability 0.210)
- correctness_risk: not_detected (confidence 0.280; detected probability 0.080)
- security_risk: not_detected (confidence 0.280; detected probability 0.030)
- maintainability_risk: not_detected (confidence 0.520; detected probability 0.130)
- no_major_issue: not_detected (confidence 0.330; detected probability 0.110)

## 107: backend/tests/test_auth.py

Scope: file; status: reviewed.

- Lines 1–65 (backend/tests/test_auth.py)
- runtime_error_risk: detected (confidence 0.440; detected probability 0.630)
- correctness_risk: insufficient_context (confidence 0.480; detected probability 0.180)
- security_risk: insufficient_context (confidence 0.310; detected probability 0.360)
- maintainability_risk: detected (confidence 0.270; detected probability 0.510)
- no_major_issue: insufficient_context (confidence 0.190; detected probability 0.380)

## 108: backend/tests/test_collectors.py

Scope: file; status: reviewed.

- Lines 1–147 (backend/tests/test_collectors.py)
- runtime_error_risk: not_detected (confidence 0.340; detected probability 0.160)
- correctness_risk: not_detected (confidence 0.310; detected probability 0.060)
- security_risk: not_detected (confidence 0.540; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.660; detected probability 0.080)
- no_major_issue: not_detected (confidence 0.430; detected probability 0.100)

## 109: backend/tests/test_delete_cascade.py

Scope: file; status: reviewed.

- Lines 1–120 (backend/tests/test_delete_cascade.py)
- runtime_error_risk: detected (confidence 0.590; detected probability 0.730)
- correctness_risk: insufficient_context (confidence 0.180; detected probability 0.440)
- security_risk: not_detected (confidence 0.270; detected probability 0.040)
- maintainability_risk: detected (confidence 0.550; detected probability 0.700)
- no_major_issue: detected (confidence 0.370; detected probability 0.580)

## 110: backend/tests/test_detector.py

Scope: file; status: reviewed.

- Lines 1–49 (backend/tests/test_detector.py)
- runtime_error_risk: insufficient_context (confidence 0.540; detected probability 0.090)
- correctness_risk: insufficient_context (confidence 0.800; detected probability 0.010)
- security_risk: not_detected (confidence 0.550; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.330; detected probability 0.030)
- no_major_issue: insufficient_context (confidence 0.520; detected probability 0.090)

## 111: backend/tests/test_eval.py

Scope: file; status: reviewed.

- Lines 1–27 (backend/tests/test_eval.py)
- runtime_error_risk: insufficient_context (confidence 0.630; detected probability 0.100)
- correctness_risk: insufficient_context (confidence 0.660; detected probability 0.010)
- security_risk: not_detected (confidence 0.450; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.260; detected probability 0.130)
- no_major_issue: insufficient_context (confidence 0.440; detected probability 0.040)

## 112: backend/tests/test_fixes.py

Scope: file; status: reviewed.

- Lines 1–95 (backend/tests/test_fixes.py)
- runtime_error_risk: detected (confidence 0.730; detected probability 0.820)
- correctness_risk: detected (confidence 0.400; detected probability 0.600)
- security_risk: insufficient_context (confidence 0.540; detected probability 0.160)
- maintainability_risk: detected (confidence 0.670; detected probability 0.780)
- no_major_issue: detected (confidence 0.380; detected probability 0.590)

## 113: backend/tests/test_golden.py

Scope: file; status: reviewed.

- Lines 1–124 (backend/tests/test_golden.py)
- runtime_error_risk: insufficient_context (confidence 0.170; detected probability 0.340)
- correctness_risk: insufficient_context (confidence 0.380; detected probability 0.040)
- security_risk: not_detected (confidence 0.480; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.520; detected probability 0.090)
- no_major_issue: not_detected (confidence 0.180; detected probability 0.110)

## 114: backend/tests/test_guards.py

Scope: file; status: reviewed.

- Lines 1–76 (backend/tests/test_guards.py)
- runtime_error_risk: not_detected (confidence 0.440; detected probability 0.060)
- correctness_risk: not_detected (confidence 0.380; detected probability 0.010)
- security_risk: not_detected (confidence 0.720; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.760; detected probability 0.020)
- no_major_issue: not_detected (confidence 0.460; detected probability 0.080)

## 115: backend/tests/test_guest_and_google.py

Scope: file; status: reviewed.

- Lines 1–421 (backend/tests/test_guest_and_google.py)
- runtime_error_risk: insufficient_context (confidence 0.220; detected probability 0.430)
- correctness_risk: insufficient_context (confidence 0.530; detected probability 0.160)
- security_risk: insufficient_context (confidence 0.480; detected probability 0.090)
- maintainability_risk: detected (confidence 0.160; detected probability 0.440)
- no_major_issue: insufficient_context (confidence 0.310; detected probability 0.310)

## 116: backend/tests/test_guest_and_google.py

Scope: file; status: reviewed.

- Lines 422–572 (backend/tests/test_guest_and_google.py)
- runtime_error_risk: detected (confidence 0.080; detected probability 0.390)
- correctness_risk: insufficient_context (confidence 0.340; detected probability 0.070)
- security_risk: not_detected (confidence 0.340; detected probability 0.040)
- maintainability_risk: not_detected (confidence 0.060; detected probability 0.330)
- no_major_issue: insufficient_context (confidence 0.180; detected probability 0.240)

## 117: backend/tests/test_hardening.py

Scope: file; status: reviewed.

- Lines 1–193 (backend/tests/test_hardening.py)
- runtime_error_risk: not_detected (confidence 0.060; detected probability 0.260)
- correctness_risk: not_detected (confidence 0.370; detected probability 0.040)
- security_risk: not_detected (confidence 0.620; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.580; detected probability 0.130)
- no_major_issue: not_detected (confidence 0.350; detected probability 0.090)

## 118: backend/tests/test_live_trace_access.py

Scope: file; status: reviewed.

- Lines 1–162 (backend/tests/test_live_trace_access.py)
- runtime_error_risk: detected (confidence 0.030; detected probability 0.350)
- correctness_risk: not_detected (confidence 0.240; detected probability 0.040)
- security_risk: insufficient_context (confidence 0.310; detected probability 0.040)
- maintainability_risk: not_detected (confidence 0.360; detected probability 0.230)
- no_major_issue: not_detected (confidence 0.150; detected probability 0.190)

## 119: backend/tests/test_live_trace_visibility.py

Scope: file; status: reviewed.

- Lines 1–114 (backend/tests/test_live_trace_visibility.py)
- runtime_error_risk: not_detected (confidence 0.350; detected probability 0.140)
- correctness_risk: not_detected (confidence 0.460; detected probability 0.040)
- security_risk: not_detected (confidence 0.640; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.560; detected probability 0.120)
- no_major_issue: not_detected (confidence 0.300; detected probability 0.140)

## 120: backend/tests/test_llm_shape_coercion.py

Scope: file; status: reviewed.

- Lines 1–111 (backend/tests/test_llm_shape_coercion.py)
- runtime_error_risk: not_detected (confidence 0.220; detected probability 0.070)
- correctness_risk: not_detected (confidence 0.340; detected probability 0.080)
- security_risk: not_detected (confidence 0.810; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.670; detected probability 0.020)
- no_major_issue: not_detected (confidence 0.270; detected probability 0.100)

## 121: backend/tests/test_model_compat.py

Scope: file; status: reviewed.

- Lines 1–152 (backend/tests/test_model_compat.py)
- runtime_error_risk: not_detected (confidence 0.460; detected probability 0.140)
- correctness_risk: not_detected (confidence 0.550; detected probability 0.040)
- security_risk: not_detected (confidence 0.820; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.720; detected probability 0.080)
- no_major_issue: not_detected (confidence 0.530; detected probability 0.110)

## 122: backend/tests/test_orchestrator.py

Scope: file; status: reviewed.

- Lines 1–71 (backend/tests/test_orchestrator.py)
- runtime_error_risk: insufficient_context (confidence 0.260; detected probability 0.230)
- correctness_risk: insufficient_context (confidence 0.450; detected probability 0.030)
- security_risk: not_detected (confidence 0.390; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.450; detected probability 0.050)
- no_major_issue: insufficient_context (confidence 0.250; detected probability 0.070)

## 123: backend/tests/test_queue_visibility.py

Scope: file; status: reviewed.

- Lines 1–136 (backend/tests/test_queue_visibility.py)
- runtime_error_risk: not_detected (confidence 0.400; detected probability 0.070)
- correctness_risk: insufficient_context (confidence 0.420; detected probability 0.020)
- security_risk: not_detected (confidence 0.340; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.650; detected probability 0.040)
- no_major_issue: not_detected (confidence 0.350; detected probability 0.070)

## 124: backend/tests/test_recommender.py

Scope: file; status: reviewed.

- Lines 1–35 (backend/tests/test_recommender.py)
- runtime_error_risk: insufficient_context (confidence 0.220; detected probability 0.050)
- correctness_risk: insufficient_context (confidence 0.420; detected probability 0.010)
- security_risk: not_detected (confidence 0.610; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.630; detected probability 0.020)
- no_major_issue: not_detected (confidence 0.260; detected probability 0.060)

## 125: backend/tests/test_review.py

Scope: file; status: reviewed.

- Lines 1–79 (backend/tests/test_review.py)
- runtime_error_risk: detected (confidence 0.160; detected probability 0.440)
- correctness_risk: insufficient_context (confidence 0.480; detected probability 0.050)
- security_risk: not_detected (confidence 0.400; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.390; detected probability 0.130)
- no_major_issue: insufficient_context (confidence 0.290; detected probability 0.120)

## 126: backend/tests/test_review_fixes.py

Scope: file; status: reviewed.

- Lines 1–172 (backend/tests/test_review_fixes.py)
- runtime_error_risk: not_detected (confidence 0.230; detected probability 0.110)
- correctness_risk: insufficient_context (confidence 0.390; detected probability 0.160)
- security_risk: insufficient_context (confidence 0.250; detected probability 0.210)
- maintainability_risk: not_detected (confidence 0.310; detected probability 0.180)
- no_major_issue: not_detected (confidence 0.180; detected probability 0.170)

## 127: backend/tests/test_semantic.py

Scope: file; status: reviewed.

- Lines 1–40 (backend/tests/test_semantic.py)
- runtime_error_risk: insufficient_context (confidence 0.330; detected probability 0.080)
- correctness_risk: insufficient_context (confidence 0.330; detected probability 0.020)
- security_risk: not_detected (confidence 0.620; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.600; detected probability 0.040)
- no_major_issue: insufficient_context (confidence 0.210; detected probability 0.090)

## 128: backend/tests/test_sources_v71.py

Scope: file; status: reviewed.

- Lines 1–82 (backend/tests/test_sources_v71.py)
- runtime_error_risk: not_detected (confidence 0.180; detected probability 0.190)
- correctness_risk: insufficient_context (confidence 0.220; detected probability 0.060)
- security_risk: not_detected (confidence 0.510; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.610; detected probability 0.060)
- no_major_issue: not_detected (confidence 0.190; detected probability 0.140)

## 129: backend/tests/test_tools.py

Scope: file; status: reviewed.

- Lines 1–80 (backend/tests/test_tools.py)
- runtime_error_risk: insufficient_context (confidence 0.450; detected probability 0.090)
- correctness_risk: insufficient_context (confidence 0.700; detected probability 0.010)
- security_risk: not_detected (confidence 0.270; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.340; detected probability 0.090)
- no_major_issue: insufficient_context (confidence 0.480; detected probability 0.040)

## 130: backend/tests/test_v10_feedback_graph.py

Scope: file; status: reviewed.

- Lines 1–372 (backend/tests/test_v10_feedback_graph.py)
- runtime_error_risk: insufficient_context (confidence 0.110; detected probability 0.210)
- correctness_risk: insufficient_context (confidence 0.520; detected probability 0.060)
- security_risk: insufficient_context (confidence 0.280; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.380; detected probability 0.080)
- no_major_issue: insufficient_context (confidence 0.320; detected probability 0.090)

## 131: backend/tests/test_v10_themes_queue.py

Scope: file; status: reviewed.

- Lines 1–296 (backend/tests/test_v10_themes_queue.py)
- runtime_error_risk: insufficient_context (confidence 0.210; detected probability 0.110)
- correctness_risk: insufficient_context (confidence 0.500; detected probability 0.040)
- security_risk: not_detected (confidence 0.360; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.440; detected probability 0.110)
- no_major_issue: not_detected (confidence 0.190; detected probability 0.100)

## 132: backend/tests/test_v11_backlog.py

Scope: file; status: reviewed.

- Lines 1–261 (backend/tests/test_v11_backlog.py)
- runtime_error_risk: not_detected (confidence 0.140; detected probability 0.150)
- correctness_risk: insufficient_context (confidence 0.590; detected probability 0.030)
- security_risk: not_detected (confidence 0.450; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.360; detected probability 0.130)
- no_major_issue: insufficient_context (confidence 0.260; detected probability 0.070)

## 133: backend/tests/test_v12_brain.py

Scope: file; status: reviewed.

- Lines 1–257 (backend/tests/test_v12_brain.py)
- runtime_error_risk: insufficient_context (confidence 0.250; detected probability 0.170)
- correctness_risk: insufficient_context (confidence 0.620; detected probability 0.020)
- security_risk: not_detected (confidence 0.450; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.290; detected probability 0.140)
- no_major_issue: insufficient_context (confidence 0.280; detected probability 0.090)

## 134: backend/tests/test_v13_cases.py

Scope: file; status: reviewed.

- Lines 1–286 (backend/tests/test_v13_cases.py)
- runtime_error_risk: not_detected (confidence 0.190; detected probability 0.220)
- correctness_risk: insufficient_context (confidence 0.450; detected probability 0.050)
- security_risk: not_detected (confidence 0.330; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.420; detected probability 0.120)
- no_major_issue: not_detected (confidence 0.230; detected probability 0.090)

## 135: backend/tests/test_v14_batch1.py

Scope: file; status: reviewed.

- Lines 1–189 (backend/tests/test_v14_batch1.py)
- runtime_error_risk: not_detected (confidence 0.210; detected probability 0.140)
- correctness_risk: insufficient_context (confidence 0.400; detected probability 0.040)
- security_risk: not_detected (confidence 0.460; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.460; detected probability 0.100)
- no_major_issue: not_detected (confidence 0.200; detected probability 0.090)

## 136: backend/tests/test_v14_batch2.py

Scope: file; status: reviewed.

- Lines 1–160 (backend/tests/test_v14_batch2.py)
- runtime_error_risk: not_detected (confidence 0.390; detected probability 0.060)
- correctness_risk: insufficient_context (confidence 0.240; detected probability 0.190)
- security_risk: not_detected (confidence 0.570; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.410; detected probability 0.080)
- no_major_issue: not_detected (confidence 0.220; detected probability 0.110)

## 137: backend/tests/test_v14_batch3.py

Scope: file; status: reviewed.

- Lines 1–98 (backend/tests/test_v14_batch3.py)
- runtime_error_risk: not_detected (confidence 0.190; detected probability 0.170)
- correctness_risk: insufficient_context (confidence 0.300; detected probability 0.170)
- security_risk: not_detected (confidence 0.490; detected probability 0.030)
- maintainability_risk: not_detected (confidence 0.340; detected probability 0.180)
- no_major_issue: not_detected (confidence 0.170; detected probability 0.170)

## 138: backend/tests/test_v14_batch4.py

Scope: file; status: reviewed.

- Lines 1–116 (backend/tests/test_v14_batch4.py)
- runtime_error_risk: detected (confidence 0.260; detected probability 0.510)
- correctness_risk: insufficient_context (confidence 0.620; detected probability 0.100)
- security_risk: insufficient_context (confidence 0.500; detected probability 0.120)
- maintainability_risk: insufficient_context (confidence 0.130; detected probability 0.410)
- no_major_issue: insufficient_context (confidence 0.110; detected probability 0.380)

## 139: backend/tests/test_v14_batch8.py

Scope: file; status: reviewed.

- Lines 1–121 (backend/tests/test_v14_batch8.py)
- runtime_error_risk: not_detected (confidence 0.320; detected probability 0.080)
- correctness_risk: insufficient_context (confidence 0.340; detected probability 0.040)
- security_risk: not_detected (confidence 0.470; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.460; detected probability 0.100)
- no_major_issue: not_detected (confidence 0.230; detected probability 0.090)

## 140: backend/tests/test_v2_agent.py

Scope: file; status: reviewed.

- Lines 1–111 (backend/tests/test_v2_agent.py)
- runtime_error_risk: insufficient_context (confidence 0.160; detected probability 0.380)
- correctness_risk: insufficient_context (confidence 0.350; detected probability 0.020)
- security_risk: not_detected (confidence 0.400; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.410; detected probability 0.080)
- no_major_issue: insufficient_context (confidence 0.280; detected probability 0.100)

## 141: backend/tests/test_v2_excel_import.py

Scope: file; status: reviewed.

- Lines 1–171 (backend/tests/test_v2_excel_import.py)
- runtime_error_risk: not_detected (confidence 0.220; detected probability 0.130)
- correctness_risk: not_detected (confidence 0.260; detected probability 0.050)
- security_risk: insufficient_context (confidence 0.310; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.570; detected probability 0.070)
- no_major_issue: not_detected (confidence 0.160; detected probability 0.170)

## 142: backend/tests/test_v2_multisource.py

Scope: file; status: reviewed.

- Lines 1–356 (backend/tests/test_v2_multisource.py)
- runtime_error_risk: not_detected (confidence 0.310; detected probability 0.140)
- correctness_risk: not_detected (confidence 0.360; detected probability 0.060)
- security_risk: not_detected (confidence 0.550; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.670; detected probability 0.090)
- no_major_issue: not_detected (confidence 0.320; detected probability 0.120)

## 143: backend/tests/test_v2_roadmap_verification.py

Scope: file; status: reviewed.

- Lines 1–265 (backend/tests/test_v2_roadmap_verification.py)
- runtime_error_risk: insufficient_context (confidence 0.180; detected probability 0.140)
- correctness_risk: insufficient_context (confidence 0.490; detected probability 0.060)
- security_risk: not_detected (confidence 0.280; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.530; detected probability 0.080)
- no_major_issue: insufficient_context (confidence 0.250; detected probability 0.070)

## 144: backend/tests/test_v2_tools.py

Scope: file; status: reviewed.

- Lines 1–44 (backend/tests/test_v2_tools.py)
- runtime_error_risk: insufficient_context (confidence 0.590; detected probability 0.120)
- correctness_risk: insufficient_context (confidence 0.830; detected probability 0.020)
- security_risk: not_detected (confidence 0.330; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.250; detected probability 0.040)
- no_major_issue: insufficient_context (confidence 0.620; detected probability 0.030)

## 145: backend/tests/test_v3.py

Scope: file; status: reviewed.

- Lines 1–195 (backend/tests/test_v3.py)
- runtime_error_risk: not_detected (confidence 0.210; detected probability 0.140)
- correctness_risk: insufficient_context (confidence 0.400; detected probability 0.030)
- security_risk: insufficient_context (confidence 0.420; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.510; detected probability 0.160)
- no_major_issue: not_detected (confidence 0.210; detected probability 0.110)

## 146: backend/tests/test_v4.py

Scope: file; status: reviewed.

- Lines 1–245 (backend/tests/test_v4.py)
- runtime_error_risk: detected (confidence 0.630; detected probability 0.760)
- correctness_risk: insufficient_context (confidence 0.340; detected probability 0.380)
- security_risk: insufficient_context (confidence 0.600; detected probability 0.110)
- maintainability_risk: detected (confidence 0.440; detected probability 0.620)
- no_major_issue: detected (confidence 0.280; detected probability 0.520)

## 147: backend/tests/test_v5.py

Scope: file; status: reviewed.

- Lines 1–166 (backend/tests/test_v5.py)
- runtime_error_risk: insufficient_context (confidence 0.180; detected probability 0.320)
- correctness_risk: insufficient_context (confidence 0.330; detected probability 0.100)
- security_risk: not_detected (confidence 0.460; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.470; detected probability 0.090)
- no_major_issue: insufficient_context (confidence 0.240; detected probability 0.120)

## 148: backend/tests/test_v5_collab.py

Scope: file; status: reviewed.

- Lines 1–421 (backend/tests/test_v5_collab.py)
- runtime_error_risk: detected (confidence 0.170; detected probability 0.450)
- correctness_risk: insufficient_context (confidence 0.350; detected probability 0.110)
- security_risk: insufficient_context (confidence 0.310; detected probability 0.040)
- maintainability_risk: detected (confidence 0.070; detected probability 0.380)
- no_major_issue: insufficient_context (confidence 0.140; detected probability 0.210)

## 149: backend/tests/test_v6.py

Scope: file; status: reviewed.

- Lines 1–168 (backend/tests/test_v6.py)
- runtime_error_risk: insufficient_context (confidence 0.150; detected probability 0.190)
- correctness_risk: insufficient_context (confidence 0.490; detected probability 0.070)
- security_risk: not_detected (confidence 0.490; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.380; detected probability 0.150)
- no_major_issue: insufficient_context (confidence 0.210; detected probability 0.100)

## 150: backend/tests/test_v6_fixwatch_chart.py

Scope: file; status: reviewed.

- Lines 1–118 (backend/tests/test_v6_fixwatch_chart.py)
- runtime_error_risk: not_detected (confidence 0.250; detected probability 0.130)
- correctness_risk: insufficient_context (confidence 0.360; detected probability 0.080)
- security_risk: not_detected (confidence 0.440; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.460; detected probability 0.080)
- no_major_issue: not_detected (confidence 0.300; detected probability 0.110)

## 151: backend/tests/test_v7.py

Scope: file; status: reviewed.

- Lines 1–172 (backend/tests/test_v7.py)
- runtime_error_risk: insufficient_context (confidence 0.140; detected probability 0.260)
- correctness_risk: insufficient_context (confidence 0.640; detected probability 0.060)
- security_risk: insufficient_context (confidence 0.600; detected probability 0.030)
- maintainability_risk: not_detected (confidence 0.270; detected probability 0.230)
- no_major_issue: insufficient_context (confidence 0.340; detected probability 0.090)

## 152: backend/tests/test_v8_eval_scoped.py

Scope: file; status: reviewed.

- Lines 1–152 (backend/tests/test_v8_eval_scoped.py)
- runtime_error_risk: insufficient_context (confidence 0.240; detected probability 0.230)
- correctness_risk: insufficient_context (confidence 0.450; detected probability 0.050)
- security_risk: not_detected (confidence 0.260; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.400; detected probability 0.130)
- no_major_issue: insufficient_context (confidence 0.410; detected probability 0.040)

## 153: backend/tests/test_v8_scoping.py

Scope: file; status: reviewed.

- Lines 1–324 (backend/tests/test_v8_scoping.py)
- runtime_error_risk: not_detected (confidence 0.160; detected probability 0.290)
- correctness_risk: not_detected (confidence 0.250; detected probability 0.090)
- security_risk: insufficient_context (confidence 0.300; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.520; detected probability 0.120)
- no_major_issue: not_detected (confidence 0.270; detected probability 0.140)

## 154: backend/tests/test_v9_portfolio.py

Scope: file; status: reviewed.

- Lines 1–349 (backend/tests/test_v9_portfolio.py)
- runtime_error_risk: insufficient_context (confidence 0.250; detected probability 0.190)
- correctness_risk: insufficient_context (confidence 0.580; detected probability 0.030)
- security_risk: not_detected (confidence 0.480; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.420; detected probability 0.100)
- no_major_issue: insufficient_context (confidence 0.340; detected probability 0.070)

## 155: backend/tests/test_v9_portfolio.py

Scope: file; status: reviewed.

- Lines 350–392 (backend/tests/test_v9_portfolio.py)
- runtime_error_risk: insufficient_context (confidence 0.460; detected probability 0.040)
- correctness_risk: insufficient_context (confidence 0.750; detected probability 0.010)
- security_risk: not_detected (confidence 0.380; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.380; detected probability 0.010)
- no_major_issue: insufficient_context (confidence 0.340; detected probability 0.020)

## 156: deploy/nginx.conf

Scope: file; status: reviewed.

- Lines 1–25 (deploy/nginx.conf)
- runtime_error_risk: not_detected (confidence 0.320; detected probability 0.110)
- correctness_risk: not_detected (confidence 0.350; detected probability 0.060)
- security_risk: not_detected (confidence 0.380; detected probability 0.050)
- maintainability_risk: not_detected (confidence 0.480; detected probability 0.180)
- no_major_issue: not_detected (confidence 0.260; detected probability 0.220)

## 157: docker-compose.yml

Scope: file; status: reviewed.

- Lines 1–60 (docker-compose.yml)
- runtime_error_risk: insufficient_context (confidence 0.080; detected probability 0.290)
- correctness_risk: insufficient_context (confidence 0.570; detected probability 0.010)
- security_risk: insufficient_context (confidence 0.460; detected probability 0.130)
- maintainability_risk: not_detected (confidence 0.080; detected probability 0.350)
- no_major_issue: insufficient_context (confidence 0.120; detected probability 0.300)

## 158: frontend/package.json

Scope: file; status: reviewed.

- Lines 1–22 (frontend/package.json)
- runtime_error_risk: not_detected (confidence 0.350; detected probability 0.030)
- correctness_risk: insufficient_context (confidence 0.660; detected probability 0.000)
- security_risk: insufficient_context (confidence 0.420; detected probability 0.000)
- maintainability_risk: insufficient_context (confidence 0.220; detected probability 0.060)
- no_major_issue: insufficient_context (confidence 0.470; detected probability 0.100)

## 159: frontend/src/App.tsx

Scope: file; status: reviewed.

- Lines 1–417 (frontend/src/App.tsx)
- runtime_error_risk: detected (confidence 0.120; detected probability 0.410)
- correctness_risk: insufficient_context (confidence 0.330; detected probability 0.150)
- security_risk: insufficient_context (confidence 0.290; detected probability 0.040)
- maintainability_risk: not_detected (confidence 0.180; detected probability 0.330)
- no_major_issue: insufficient_context (confidence 0.100; detected probability 0.240)

## 160: frontend/src/App.tsx

Scope: file; status: reviewed.

- Lines 418–487 (frontend/src/App.tsx)
- runtime_error_risk: detected (confidence 0.280; detected probability 0.520)
- correctness_risk: detected (confidence 0.260; detected probability 0.510)
- security_risk: not_detected (confidence 0.320; detected probability 0.020)
- maintainability_risk: detected (confidence 0.240; detected probability 0.490)
- no_major_issue: not_detected (confidence 0.140; detected probability 0.360)

## 161: frontend/src/api.ts

Scope: file; status: reviewed.

- Lines 1–650 (frontend/src/api.ts)
- runtime_error_risk: detected (confidence 0.180; detected probability 0.460)
- correctness_risk: insufficient_context (confidence 0.340; detected probability 0.340)
- security_risk: insufficient_context (confidence 0.340; detected probability 0.270)
- maintainability_risk: detected (confidence 0.450; detected probability 0.630)
- no_major_issue: detected (confidence 0.130; detected probability 0.420)

## 162: frontend/src/api.ts

Scope: file; status: reviewed.

- Lines 651–954 (frontend/src/api.ts)
- runtime_error_risk: detected (confidence 0.460; detected probability 0.640)
- correctness_risk: detected (confidence 0.620; detected probability 0.740)
- security_risk: insufficient_context (confidence 0.240; detected probability 0.320)
- maintainability_risk: detected (confidence 0.760; detected probability 0.840)
- no_major_issue: detected (confidence 0.410; detected probability 0.610)

## 163: frontend/src/components/CaseCard.tsx

Scope: file; status: reviewed.

- Lines 1–148 (frontend/src/components/CaseCard.tsx)
- runtime_error_risk: not_detected (confidence 0.100; detected probability 0.290)
- correctness_risk: not_detected (confidence 0.430; detected probability 0.010)
- security_risk: not_detected (confidence 0.810; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.610; detected probability 0.100)
- no_major_issue: not_detected (confidence 0.270; detected probability 0.150)

## 164: frontend/src/components/DeleteProductModal.tsx

Scope: file; status: reviewed.

- Lines 1–153 (frontend/src/components/DeleteProductModal.tsx)
- runtime_error_risk: not_detected (confidence 0.190; detected probability 0.210)
- correctness_risk: not_detected (confidence 0.530; detected probability 0.030)
- security_risk: not_detected (confidence 0.410; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.590; detected probability 0.130)
- no_major_issue: not_detected (confidence 0.360; detected probability 0.180)

## 165: frontend/src/components/ErrorBoundary.tsx

Scope: file; status: reviewed.

- Lines 1–67 (frontend/src/components/ErrorBoundary.tsx)
- runtime_error_risk: not_detected (confidence 0.350; detected probability 0.170)
- correctness_risk: not_detected (confidence 0.710; detected probability 0.010)
- security_risk: not_detected (confidence 0.930; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.740; detected probability 0.090)
- no_major_issue: not_detected (confidence 0.430; detected probability 0.180)

## 166: frontend/src/components/EvidenceSheet.tsx

Scope: file; status: reviewed.

- Lines 1–79 (frontend/src/components/EvidenceSheet.tsx)
- runtime_error_risk: not_detected (confidence 0.470; detected probability 0.130)
- correctness_risk: not_detected (confidence 0.720; detected probability 0.030)
- security_risk: not_detected (confidence 0.780; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.710; detected probability 0.100)
- no_major_issue: not_detected (confidence 0.360; detected probability 0.190)

## 167: frontend/src/components/GoogleButton.tsx

Scope: file; status: reviewed.

- Lines 1–166 (frontend/src/components/GoogleButton.tsx)
- runtime_error_risk: detected (confidence 0.240; detected probability 0.490)
- correctness_risk: not_detected (confidence 0.570; detected probability 0.060)
- security_risk: not_detected (confidence 0.650; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.570; detected probability 0.230)
- no_major_issue: not_detected (confidence 0.480; detected probability 0.260)

## 168: frontend/src/components/Icon.tsx

Scope: file; status: reviewed.

- Lines 1–123 (frontend/src/components/Icon.tsx)
- runtime_error_risk: not_detected (confidence 0.790; detected probability 0.100)
- correctness_risk: not_detected (confidence 0.800; detected probability 0.010)
- security_risk: not_detected (confidence 0.930; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.600; detected probability 0.210)
- no_major_issue: not_detected (confidence 0.590; detected probability 0.220)

## 169: frontend/src/components/NewCaseModal.tsx

Scope: file; status: reviewed.

- Lines 1–129 (frontend/src/components/NewCaseModal.tsx)
- runtime_error_risk: detected (confidence 0.330; detected probability 0.550)
- correctness_risk: not_detected (confidence 0.350; detected probability 0.160)
- security_risk: not_detected (confidence 0.570; detected probability 0.010)
- maintainability_risk: detected (confidence 0.350; detected probability 0.570)
- no_major_issue: detected (confidence 0.210; detected probability 0.470)

## 170: frontend/src/components/Sidebar.tsx

Scope: file; status: reviewed.

- Lines 1–399 (frontend/src/components/Sidebar.tsx)
- runtime_error_risk: not_detected (confidence 0.120; detected probability 0.200)
- correctness_risk: insufficient_context (confidence 0.260; detected probability 0.080)
- security_risk: not_detected (confidence 0.390; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.290; detected probability 0.180)
- no_major_issue: insufficient_context (confidence 0.300; detected probability 0.080)

## 171: frontend/src/components/Sidebar.tsx

Scope: file; status: reviewed.

- Lines 400–432 (frontend/src/components/Sidebar.tsx)
- runtime_error_risk: not_detected (confidence 0.390; detected probability 0.020)
- correctness_risk: not_detected (confidence 0.680; detected probability 0.000)
- security_risk: not_detected (confidence 0.870; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.820; detected probability 0.010)
- no_major_issue: not_detected (confidence 0.490; detected probability 0.050)

## 172: frontend/src/components/ThemeToggle.tsx

Scope: file; status: reviewed.

- Lines 1–24 (frontend/src/components/ThemeToggle.tsx)
- runtime_error_risk: not_detected (confidence 0.350; detected probability 0.010)
- correctness_risk: not_detected (confidence 0.640; detected probability 0.000)
- security_risk: not_detected (confidence 0.950; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.730; detected probability 0.000)
- no_major_issue: not_detected (confidence 0.290; detected probability 0.080)

## 173: frontend/src/components/Toast.tsx

Scope: file; status: reviewed.

- Lines 1–159 (frontend/src/components/Toast.tsx)
- runtime_error_risk: not_detected (confidence 0.200; detected probability 0.400)
- correctness_risk: not_detected (confidence 0.540; detected probability 0.120)
- security_risk: not_detected (confidence 0.860; detected probability 0.030)
- maintainability_risk: detected (confidence 0.440; detected probability 0.630)
- no_major_issue: not_detected (confidence 0.290; detected probability 0.340)

## 174: frontend/src/format.ts

Scope: file; status: reviewed.

- Lines 1–65 (frontend/src/format.ts)
- runtime_error_risk: not_detected (confidence 0.780; detected probability 0.120)
- correctness_risk: not_detected (confidence 0.530; detected probability 0.140)
- security_risk: not_detected (confidence 0.960; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.810; detected probability 0.060)
- no_major_issue: not_detected (confidence 0.570; detected probability 0.220)

## 175: frontend/src/hooks.ts

Scope: file; status: reviewed.

- Lines 1–301 (frontend/src/hooks.ts)
- runtime_error_risk: detected (confidence 0.340; detected probability 0.560)
- correctness_risk: not_detected (confidence 0.390; detected probability 0.280)
- security_risk: not_detected (confidence 0.620; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.470; detected probability 0.300)
- no_major_issue: not_detected (confidence 0.460; detected probability 0.260)

## 176: frontend/src/main.tsx

Scope: file; status: reviewed.

- Lines 1–10 (frontend/src/main.tsx)
- runtime_error_risk: insufficient_context (confidence 0.160; detected probability 0.310)
- correctness_risk: insufficient_context (confidence 0.440; detected probability 0.000)
- security_risk: not_detected (confidence 0.310; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.560; detected probability 0.000)
- no_major_issue: not_detected (confidence 0.230; detected probability 0.070)

## 177: frontend/src/nav.ts

Scope: file; status: reviewed.

- Lines 1–169 (frontend/src/nav.ts)
- runtime_error_risk: not_detected (confidence 0.540; detected probability 0.260)
- correctness_risk: not_detected (confidence 0.260; detected probability 0.280)
- security_risk: not_detected (confidence 0.540; detected probability 0.130)
- maintainability_risk: not_detected (confidence 0.490; detected probability 0.290)
- no_major_issue: not_detected (confidence 0.430; detected probability 0.320)

## 178: frontend/src/router.ts

Scope: file; status: reviewed.

- Lines 1–147 (frontend/src/router.ts)
- runtime_error_risk: not_detected (confidence 0.360; detected probability 0.230)
- correctness_risk: not_detected (confidence 0.470; detected probability 0.110)
- security_risk: not_detected (confidence 0.790; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.540; detected probability 0.230)
- no_major_issue: not_detected (confidence 0.490; detected probability 0.200)

## 179: frontend/src/screens/Backlog.tsx

Scope: file; status: reviewed.

- Lines 1–291 (frontend/src/screens/Backlog.tsx)
- runtime_error_risk: detected (confidence 0.380; detected probability 0.590)
- correctness_risk: detected (confidence 0.670; detected probability 0.780)
- security_risk: not_detected (confidence 0.400; detected probability 0.010)
- maintainability_risk: detected (confidence 0.710; detected probability 0.800)
- no_major_issue: detected (confidence 0.380; detected probability 0.590)

## 180: frontend/src/screens/Brain.tsx

Scope: file; status: reviewed.

- Lines 1–271 (frontend/src/screens/Brain.tsx)
- runtime_error_risk: not_detected (confidence 0.190; detected probability 0.280)
- correctness_risk: not_detected (confidence 0.270; detected probability 0.040)
- security_risk: not_detected (confidence 0.330; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.610; detected probability 0.110)
- no_major_issue: not_detected (confidence 0.360; detected probability 0.130)

## 181: frontend/src/screens/Calibration.tsx

Scope: file; status: reviewed.

- Lines 1–173 (frontend/src/screens/Calibration.tsx)
- runtime_error_risk: not_detected (confidence 0.240; detected probability 0.280)
- correctness_risk: not_detected (confidence 0.340; detected probability 0.050)
- security_risk: not_detected (confidence 0.750; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.750; detected probability 0.070)
- no_major_issue: not_detected (confidence 0.490; detected probability 0.090)

## 182: frontend/src/screens/CaseDetail.tsx

Scope: file; status: reviewed.

- Lines 1–251 (frontend/src/screens/CaseDetail.tsx)
- runtime_error_risk: detected (confidence 0.100; detected probability 0.400)
- correctness_risk: not_detected (confidence 0.460; detected probability 0.160)
- security_risk: not_detected (confidence 0.440; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.570; detected probability 0.210)
- no_major_issue: not_detected (confidence 0.480; detected probability 0.130)

## 183: frontend/src/screens/Cases.tsx

Scope: file; status: reviewed.

- Lines 1–416 (frontend/src/screens/Cases.tsx)
- runtime_error_risk: insufficient_context (confidence 0.090; detected probability 0.350)
- correctness_risk: insufficient_context (confidence 0.260; detected probability 0.160)
- security_risk: insufficient_context (confidence 0.290; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.180; detected probability 0.270)
- no_major_issue: insufficient_context (confidence 0.150; detected probability 0.180)

## 184: frontend/src/screens/Cases.tsx

Scope: file; status: reviewed.

- Lines 417–582 (frontend/src/screens/Cases.tsx)
- runtime_error_risk: not_detected (confidence 0.350; detected probability 0.080)
- correctness_risk: insufficient_context (confidence 0.250; detected probability 0.010)
- security_risk: not_detected (confidence 0.580; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.680; detected probability 0.040)
- no_major_issue: not_detected (confidence 0.300; detected probability 0.060)

## 185: frontend/src/screens/Chat.tsx

Scope: file; status: reviewed.

- Lines 1–199 (frontend/src/screens/Chat.tsx)
- runtime_error_risk: not_detected (confidence 0.100; detected probability 0.390)
- correctness_risk: detected (confidence 0.200; detected probability 0.470)
- security_risk: not_detected (confidence 0.410; detected probability 0.030)
- maintainability_risk: detected (confidence 0.350; detected probability 0.570)
- no_major_issue: detected (confidence 0.160; detected probability 0.440)

## 186: frontend/src/screens/Costs.tsx

Scope: file; status: reviewed.

- Lines 1–120 (frontend/src/screens/Costs.tsx)
- runtime_error_risk: detected (confidence 0.310; detected probability 0.540)
- correctness_risk: detected (confidence 0.210; detected probability 0.480)
- security_risk: not_detected (confidence 0.440; detected probability 0.050)
- maintainability_risk: detected (confidence 0.370; detected probability 0.580)
- no_major_issue: not_detected (confidence 0.070; detected probability 0.350)

## 187: frontend/src/screens/Login.tsx

Scope: file; status: reviewed.

- Lines 1–354 (frontend/src/screens/Login.tsx)
- runtime_error_risk: detected (confidence 0.190; detected probability 0.470)
- correctness_risk: not_detected (confidence 0.430; detected probability 0.030)
- security_risk: not_detected (confidence 0.260; detected probability 0.030)
- maintainability_risk: not_detected (confidence 0.550; detected probability 0.200)
- no_major_issue: not_detected (confidence 0.200; detected probability 0.190)

## 188: frontend/src/screens/Onboarding.tsx

Scope: file; status: reviewed.

- Lines 1–405 (frontend/src/screens/Onboarding.tsx)
- runtime_error_risk: not_detected (confidence 0.040; detected probability 0.360)
- correctness_risk: insufficient_context (confidence 0.200; detected probability 0.240)
- security_risk: not_detected (confidence 0.430; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.210; detected probability 0.270)
- no_major_issue: not_detected (confidence 0.110; detected probability 0.230)

## 189: frontend/src/screens/Onboarding.tsx

Scope: file; status: reviewed.

- Lines 406–603 (frontend/src/screens/Onboarding.tsx)
- runtime_error_risk: not_detected (confidence 0.200; detected probability 0.230)
- correctness_risk: insufficient_context (confidence 0.290; detected probability 0.050)
- security_risk: not_detected (confidence 0.760; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.540; detected probability 0.150)
- no_major_issue: not_detected (confidence 0.290; detected probability 0.120)

## 190: frontend/src/screens/Patterns.tsx

Scope: file; status: reviewed.

- Lines 1–100 (frontend/src/screens/Patterns.tsx)
- runtime_error_risk: not_detected (confidence 0.050; detected probability 0.290)
- correctness_risk: not_detected (confidence 0.310; detected probability 0.010)
- security_risk: not_detected (confidence 0.580; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.570; detected probability 0.100)
- no_major_issue: not_detected (confidence 0.260; detected probability 0.100)

## 191: frontend/src/screens/Portfolio.tsx

Scope: file; status: reviewed.

- Lines 1–322 (frontend/src/screens/Portfolio.tsx)
- runtime_error_risk: detected (confidence 0.070; detected probability 0.390)
- correctness_risk: insufficient_context (confidence 0.300; detected probability 0.040)
- security_risk: not_detected (confidence 0.570; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.730; detected probability 0.090)
- no_major_issue: not_detected (confidence 0.400; detected probability 0.160)

## 192: frontend/src/screens/Settings.tsx

Scope: file; status: reviewed.

- Lines 1–207 (frontend/src/screens/Settings.tsx)
- runtime_error_risk: not_detected (confidence 0.150; detected probability 0.300)
- correctness_risk: insufficient_context (confidence 0.440; detected probability 0.050)
- security_risk: not_detected (confidence 0.330; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.650; detected probability 0.130)
- no_major_issue: not_detected (confidence 0.300; detected probability 0.140)

## 193: frontend/src/screens/Sources.tsx

Scope: file; status: reviewed.

- Lines 1–283 (frontend/src/screens/Sources.tsx)
- runtime_error_risk: detected (confidence 0.290; detected probability 0.520)
- correctness_risk: insufficient_context (confidence 0.170; detected probability 0.110)
- security_risk: insufficient_context (confidence 0.510; detected probability 0.040)
- maintainability_risk: not_detected (confidence 0.360; detected probability 0.310)
- no_major_issue: not_detected (confidence 0.200; detected probability 0.250)

## 194: frontend/src/screens/Today.tsx

Scope: file; status: reviewed.

- Lines 1–376 (frontend/src/screens/Today.tsx)
- runtime_error_risk: not_detected (confidence 0.200; detected probability 0.250)
- correctness_risk: detected (confidence 0.410; detected probability 0.610)
- security_risk: insufficient_context (confidence 0.260; detected probability 0.010)
- maintainability_risk: detected (confidence 0.590; detected probability 0.720)
- no_major_issue: detected (confidence 0.000; detected probability 0.340)

## 195: frontend/src/screens/Today.tsx

Scope: file; status: reviewed.

- Lines 377–636 (frontend/src/screens/Today.tsx)
- runtime_error_risk: not_detected (confidence 0.260; detected probability 0.190)
- correctness_risk: insufficient_context (confidence 0.390; detected probability 0.040)
- security_risk: not_detected (confidence 0.630; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.600; detected probability 0.110)
- no_major_issue: not_detected (confidence 0.280; detected probability 0.140)

## 196: frontend/src/screens/case/DiscussionTab.tsx

Scope: file; status: reviewed.

- Lines 1–188 (frontend/src/screens/case/DiscussionTab.tsx)
- runtime_error_risk: not_detected (confidence 0.210; detected probability 0.300)
- correctness_risk: not_detected (confidence 0.530; detected probability 0.060)
- security_risk: not_detected (confidence 0.280; detected probability 0.070)
- maintainability_risk: not_detected (confidence 0.470; detected probability 0.260)
- no_major_issue: not_detected (confidence 0.230; detected probability 0.250)

## 197: frontend/src/screens/case/EngineeringTab.tsx

Scope: file; status: reviewed.

- Lines 1–189 (frontend/src/screens/case/EngineeringTab.tsx)
- runtime_error_risk: insufficient_context (confidence 0.070; detected probability 0.310)
- correctness_risk: insufficient_context (confidence 0.360; detected probability 0.010)
- security_risk: not_detected (confidence 0.530; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.680; detected probability 0.050)
- no_major_issue: not_detected (confidence 0.260; detected probability 0.100)

## 198: frontend/src/screens/case/EvidenceTab.tsx

Scope: file; status: reviewed.

- Lines 1–86 (frontend/src/screens/case/EvidenceTab.tsx)
- runtime_error_risk: not_detected (confidence 0.350; detected probability 0.170)
- correctness_risk: not_detected (confidence 0.560; detected probability 0.050)
- security_risk: not_detected (confidence 0.770; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.730; detected probability 0.050)
- no_major_issue: not_detected (confidence 0.490; detected probability 0.110)

## 199: frontend/src/screens/case/FindingTab.tsx

Scope: file; status: reviewed.

- Lines 1–406 (frontend/src/screens/case/FindingTab.tsx)
- runtime_error_risk: detected (confidence 0.090; detected probability 0.390)
- correctness_risk: insufficient_context (confidence 0.560; detected probability 0.040)
- security_risk: not_detected (confidence 0.340; detected probability 0.020)
- maintainability_risk: detected (confidence 0.250; detected probability 0.500)
- no_major_issue: insufficient_context (confidence 0.180; detected probability 0.360)

## 200: frontend/src/screens/case/FindingTab.tsx

Scope: file; status: reviewed.

- Lines 407–479 (frontend/src/screens/case/FindingTab.tsx)
- runtime_error_risk: not_detected (confidence 0.350; detected probability 0.030)
- correctness_risk: not_detected (confidence 0.340; detected probability 0.000)
- security_risk: not_detected (confidence 0.640; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.610; detected probability 0.030)
- no_major_issue: not_detected (confidence 0.410; detected probability 0.070)

## 201: frontend/src/screens/case/HistoryTab.tsx

Scope: file; status: reviewed.

- Lines 1–91 (frontend/src/screens/case/HistoryTab.tsx)
- runtime_error_risk: not_detected (confidence 0.580; detected probability 0.080)
- correctness_risk: not_detected (confidence 0.540; detected probability 0.020)
- security_risk: not_detected (confidence 0.760; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.710; detected probability 0.070)
- no_major_issue: not_detected (confidence 0.520; detected probability 0.080)

## 202: frontend/src/screens/case/TraceTab.tsx

Scope: file; status: reviewed.

- Lines 1–386 (frontend/src/screens/case/TraceTab.tsx)
- runtime_error_risk: not_detected (confidence 0.090; detected probability 0.250)
- correctness_risk: insufficient_context (confidence 0.190; detected probability 0.150)
- security_risk: not_detected (confidence 0.470; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.170; detected probability 0.310)
- no_major_issue: insufficient_context (confidence 0.190; detected probability 0.190)

## 203: frontend/src/screens/case/TraceTab.tsx

Scope: file; status: reviewed.

- Lines 387–423 (frontend/src/screens/case/TraceTab.tsx)
- runtime_error_risk: not_detected (confidence 0.450; detected probability 0.040)
- correctness_risk: not_detected (confidence 0.530; detected probability 0.000)
- security_risk: not_detected (confidence 0.760; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.590; detected probability 0.010)
- no_major_issue: not_detected (confidence 0.420; detected probability 0.030)

## 204: frontend/src/sidebarState.ts

Scope: file; status: reviewed.

- Lines 1–22 (frontend/src/sidebarState.ts)
- runtime_error_risk: not_detected (confidence 0.730; detected probability 0.140)
- correctness_risk: not_detected (confidence 0.720; detected probability 0.030)
- security_risk: not_detected (confidence 0.970; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.820; detected probability 0.030)
- no_major_issue: not_detected (confidence 0.720; detected probability 0.140)

## 205: frontend/src/status.ts

Scope: file; status: reviewed.

- Lines 1–88 (frontend/src/status.ts)
- runtime_error_risk: not_detected (confidence 0.240; detected probability 0.140)
- correctness_risk: not_detected (confidence 0.590; detected probability 0.030)
- security_risk: not_detected (confidence 0.860; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.520; detected probability 0.210)
- no_major_issue: not_detected (confidence 0.390; detected probability 0.120)

## 206: frontend/src/theme.ts

Scope: file; status: reviewed.

- Lines 1–136 (frontend/src/theme.ts)
- runtime_error_risk: not_detected (confidence 0.750; detected probability 0.020)
- correctness_risk: not_detected (confidence 0.640; detected probability 0.010)
- security_risk: not_detected (confidence 0.930; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.670; detected probability 0.030)
- no_major_issue: not_detected (confidence 0.440; detected probability 0.110)

## 207: frontend/src/themeMode.ts

Scope: file; status: reviewed.

- Lines 1–43 (frontend/src/themeMode.ts)
- runtime_error_risk: not_detected (confidence 0.580; detected probability 0.240)
- correctness_risk: not_detected (confidence 0.730; detected probability 0.040)
- security_risk: not_detected (confidence 0.980; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.780; detected probability 0.100)
- no_major_issue: not_detected (confidence 0.690; detected probability 0.160)

## 208: frontend/src/ui.tsx

Scope: file; status: reviewed.

- Lines 1–594 (frontend/src/ui.tsx)
- runtime_error_risk: not_detected (confidence 0.290; detected probability 0.180)
- correctness_risk: not_detected (confidence 0.240; detected probability 0.050)
- security_risk: not_detected (confidence 0.580; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.390; detected probability 0.110)
- no_major_issue: insufficient_context (confidence 0.250; detected probability 0.120)

## 209: frontend/src/ui.tsx

Scope: file; status: reviewed.

- Lines 595–677 (frontend/src/ui.tsx)
- runtime_error_risk: not_detected (confidence 0.480; detected probability 0.030)
- correctness_risk: not_detected (confidence 0.640; detected probability 0.000)
- security_risk: not_detected (confidence 0.830; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.680; detected probability 0.010)
- no_major_issue: not_detected (confidence 0.360; detected probability 0.060)

## 210: frontend/tsconfig.json

Scope: file; status: reviewed.

- Lines 1–14 (frontend/tsconfig.json)
- runtime_error_risk: not_detected (confidence 0.630; detected probability 0.000)
- correctness_risk: insufficient_context (confidence 0.440; detected probability 0.000)
- security_risk: not_detected (confidence 0.520; detected probability 0.000)
- maintainability_risk: not_detected (confidence 0.730; detected probability 0.000)
- no_major_issue: not_detected (confidence 0.320; detected probability 0.140)

## 211: frontend/vite.config.ts

Scope: file; status: reviewed.

- Lines 1–16 (frontend/vite.config.ts)
- runtime_error_risk: not_detected (confidence 0.600; detected probability 0.060)
- correctness_risk: not_detected (confidence 0.430; detected probability 0.030)
- security_risk: not_detected (confidence 0.630; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.650; detected probability 0.050)
- no_major_issue: not_detected (confidence 0.370; detected probability 0.180)

## 212: backend/echolens/api/app.py, backend/echolens/auth.py

Scope: authentication; status: reviewed.

- Lines 1–199 (backend/echolens/api/app.py)
- Lines 1–149 (backend/echolens/auth.py)
- runtime_error_risk: detected (confidence 0.460; detected probability 0.640)
- correctness_risk: detected (confidence 0.150; detected probability 0.440)
- security_risk: detected (confidence 0.090; detected probability 0.400)
- maintainability_risk: detected (confidence 0.450; detected probability 0.630)
- no_major_issue: detected (confidence 0.200; detected probability 0.470)

## 213: backend/echolens/api/app.py, backend/echolens/auth.py

Scope: authentication; status: reviewed.

- Lines 399–602 (backend/echolens/api/app.py)
- Lines 1–149 (backend/echolens/auth.py)
- runtime_error_risk: detected (confidence 0.460; detected probability 0.640)
- correctness_risk: not_detected (confidence 0.180; detected probability 0.320)
- security_risk: not_detected (confidence 0.240; detected probability 0.310)
- maintainability_risk: detected (confidence 0.280; detected probability 0.510)
- no_major_issue: not_detected (confidence 0.130; detected probability 0.380)

## 214: backend/echolens/api/app.py, backend/echolens/auth.py

Scope: authentication; status: reviewed.

- Lines 808–1001 (backend/echolens/api/app.py)
- Lines 1–149 (backend/echolens/auth.py)
- runtime_error_risk: detected (confidence 0.570; detected probability 0.710)
- correctness_risk: detected (confidence 0.370; detected probability 0.580)
- security_risk: detected (confidence 0.180; detected probability 0.450)
- maintainability_risk: detected (confidence 0.570; detected probability 0.710)
- no_major_issue: detected (confidence 0.250; detected probability 0.500)

## 215: backend/echolens/api/app.py, backend/echolens/auth.py

Scope: authentication; status: reviewed.

- Lines 1197–1393 (backend/echolens/api/app.py)
- Lines 1–149 (backend/echolens/auth.py)
- runtime_error_risk: detected (confidence 0.370; detected probability 0.580)
- correctness_risk: detected (confidence 0.080; detected probability 0.390)
- security_risk: detected (confidence 0.100; detected probability 0.400)
- maintainability_risk: detected (confidence 0.450; detected probability 0.630)
- no_major_issue: detected (confidence 0.200; detected probability 0.470)

## 216: backend/echolens/api/app.py, backend/echolens/auth.py

Scope: authentication; status: reviewed.

- Lines 1592–1794 (backend/echolens/api/app.py)
- Lines 1–149 (backend/echolens/auth.py)
- runtime_error_risk: detected (confidence 0.330; detected probability 0.550)
- correctness_risk: not_detected (confidence 0.050; detected probability 0.350)
- security_risk: not_detected (confidence 0.130; detected probability 0.250)
- maintainability_risk: detected (confidence 0.340; detected probability 0.560)
- no_major_issue: detected (confidence 0.110; detected probability 0.400)

## 217: backend/echolens/api/app.py, backend/echolens/auth.py

Scope: authentication; status: reviewed.

- Lines 1998–2192 (backend/echolens/api/app.py)
- Lines 1–149 (backend/echolens/auth.py)
- runtime_error_risk: detected (confidence 0.480; detected probability 0.660)
- correctness_risk: detected (confidence 0.530; detected probability 0.690)
- security_risk: detected (confidence 0.300; detected probability 0.530)
- maintainability_risk: detected (confidence 0.730; detected probability 0.820)
- no_major_issue: detected (confidence 0.270; detected probability 0.520)

## 218: backend/echolens/api/app.py, backend/echolens/auth.py

Scope: authentication; status: reviewed.

- Lines 2389–2580 (backend/echolens/api/app.py)
- Lines 1–149 (backend/echolens/auth.py)
- runtime_error_risk: detected (confidence 0.580; detected probability 0.720)
- correctness_risk: detected (confidence 0.430; detected probability 0.620)
- security_risk: detected (confidence 0.060; detected probability 0.370)
- maintainability_risk: detected (confidence 0.680; detected probability 0.780)
- no_major_issue: detected (confidence 0.390; detected probability 0.600)

## 219: backend/echolens/api/app.py, backend/echolens/auth.py

Scope: authentication; status: reviewed.

- Lines 2773–2959 (backend/echolens/api/app.py)
- Lines 1–149 (backend/echolens/auth.py)
- runtime_error_risk: detected (confidence 0.490; detected probability 0.650)
- correctness_risk: detected (confidence 0.660; detected probability 0.770)
- security_risk: insufficient_context (confidence 0.060; detected probability 0.370)
- maintainability_risk: detected (confidence 0.810; detected probability 0.880)
- no_major_issue: detected (confidence 0.330; detected probability 0.560)

## 220: backend/echolens/auth.py, frontend/src/api.ts

Scope: authentication; status: reviewed.

- Lines 1–149 (backend/echolens/auth.py)
- Lines 1–325 (frontend/src/api.ts)
- runtime_error_risk: detected (confidence 0.440; detected probability 0.630)
- correctness_risk: detected (confidence 0.210; detected probability 0.470)
- security_risk: detected (confidence 0.270; detected probability 0.510)
- maintainability_risk: detected (confidence 0.630; detected probability 0.750)
- no_major_issue: detected (confidence 0.170; detected probability 0.450)

## 221: backend/echolens/auth.py, frontend/src/api.ts

Scope: authentication; status: reviewed.

- Lines 1–149 (backend/echolens/auth.py)
- Lines 651–802 (frontend/src/api.ts)
- runtime_error_risk: detected (confidence 0.430; detected probability 0.620)
- correctness_risk: detected (confidence 0.100; detected probability 0.400)
- security_risk: not_detected (confidence 0.020; detected probability 0.340)
- maintainability_risk: detected (confidence 0.410; detected probability 0.610)
- no_major_issue: not_detected (confidence 0.080; detected probability 0.380)

## 222: frontend/src/api.ts, frontend/src/screens/Login.tsx

Scope: authentication; status: reviewed.

- Lines 1–325 (frontend/src/api.ts)
- Lines 1–177 (frontend/src/screens/Login.tsx)
- runtime_error_risk: insufficient_context (confidence 0.150; detected probability 0.420)
- correctness_risk: insufficient_context (confidence 0.510; detected probability 0.230)
- security_risk: insufficient_context (confidence 0.470; detected probability 0.290)
- maintainability_risk: detected (confidence 0.330; detected probability 0.560)
- no_major_issue: insufficient_context (confidence 0.210; detected probability 0.390)

## 223: frontend/src/api.ts, frontend/src/screens/Login.tsx

Scope: authentication; status: reviewed.

- Lines 651–802 (frontend/src/api.ts)
- Lines 1–177 (frontend/src/screens/Login.tsx)
- runtime_error_risk: detected (confidence 0.370; detected probability 0.580)
- correctness_risk: insufficient_context (confidence 0.300; detected probability 0.240)
- security_risk: insufficient_context (confidence 0.610; detected probability 0.140)
- maintainability_risk: detected (confidence 0.360; detected probability 0.570)
- no_major_issue: insufficient_context (confidence 0.190; detected probability 0.340)

## 224: backend/echolens/investigator/graph.py, backend/echolens/investigator/guards.py

Scope: investigation_and_budget; status: reviewed.

- Lines 1–188 (backend/echolens/investigator/graph.py)
- Lines 1–197 (backend/echolens/investigator/guards.py)
- runtime_error_risk: detected (confidence 0.340; detected probability 0.560)
- correctness_risk: detected (confidence 0.180; detected probability 0.460)
- security_risk: not_detected (confidence 0.230; detected probability 0.080)
- maintainability_risk: detected (confidence 0.370; detected probability 0.580)
- no_major_issue: insufficient_context (confidence 0.090; detected probability 0.370)

## 225: backend/echolens/investigator/graph.py, backend/echolens/investigator/guards.py

Scope: investigation_and_budget; status: reviewed.

- Lines 378–540 (backend/echolens/investigator/graph.py)
- Lines 1–197 (backend/echolens/investigator/guards.py)
- runtime_error_risk: detected (confidence 0.170; detected probability 0.450)
- correctness_risk: detected (confidence 0.230; detected probability 0.490)
- security_risk: insufficient_context (confidence 0.270; detected probability 0.020)
- maintainability_risk: detected (confidence 0.220; detected probability 0.480)
- no_major_issue: insufficient_context (confidence 0.020; detected probability 0.340)

## 226: backend/echolens/investigator/graph.py, backend/echolens/investigator/guards.py

Scope: investigation_and_budget; status: reviewed.

- Lines 705–808 (backend/echolens/investigator/graph.py)
- Lines 1–197 (backend/echolens/investigator/guards.py)
- runtime_error_risk: insufficient_context (confidence 0.070; detected probability 0.320)
- correctness_risk: insufficient_context (confidence 0.150; detected probability 0.330)
- security_risk: insufficient_context (confidence 0.250; detected probability 0.010)
- maintainability_risk: detected (confidence 0.160; detected probability 0.440)
- no_major_issue: insufficient_context (confidence 0.080; detected probability 0.270)

## 227: backend/echolens/investigator/guards.py, backend/echolens/investigator/memory.py

Scope: investigation_and_budget; status: reviewed.

- Lines 1–197 (backend/echolens/investigator/guards.py)
- Lines 1–69 (backend/echolens/investigator/memory.py)
- runtime_error_risk: detected (confidence 0.100; detected probability 0.400)
- correctness_risk: detected (confidence 0.100; detected probability 0.400)
- security_risk: not_detected (confidence 0.460; detected probability 0.010)
- maintainability_risk: detected (confidence 0.180; detected probability 0.450)
- no_major_issue: not_detected (confidence 0.090; detected probability 0.310)

## 228: backend/echolens/investigator/memory.py, backend/echolens/investigator/prompts.py

Scope: investigation_and_budget; status: reviewed.

- Lines 1–69 (backend/echolens/investigator/memory.py)
- Lines 1–209 (backend/echolens/investigator/prompts.py)
- runtime_error_risk: detected (confidence 0.340; detected probability 0.560)
- correctness_risk: insufficient_context (confidence 0.490; detected probability 0.150)
- security_risk: insufficient_context (confidence 0.270; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.290; detected probability 0.280)
- no_major_issue: insufficient_context (confidence 0.110; detected probability 0.200)

## 229: backend/echolens/investigator/prompts.py, backend/echolens/investigator/recover.py

Scope: investigation_and_budget; status: reviewed.

- Lines 1–209 (backend/echolens/investigator/prompts.py)
- Lines 1–54 (backend/echolens/investigator/recover.py)
- runtime_error_risk: insufficient_context (confidence 0.100; detected probability 0.260)
- correctness_risk: insufficient_context (confidence 0.430; detected probability 0.170)
- security_risk: insufficient_context (confidence 0.410; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.290; detected probability 0.260)
- no_major_issue: insufficient_context (confidence 0.150; detected probability 0.200)

## 230: backend/echolens/investigator/recover.py, backend/echolens/investigator/specialists.py

Scope: investigation_and_budget; status: reviewed.

- Lines 1–54 (backend/echolens/investigator/recover.py)
- Lines 1–80 (backend/echolens/investigator/specialists.py)
- runtime_error_risk: not_detected (confidence 0.030; detected probability 0.310)
- correctness_risk: insufficient_context (confidence 0.360; detected probability 0.200)
- security_risk: not_detected (confidence 0.370; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.310; detected probability 0.220)
- no_major_issue: not_detected (confidence 0.110; detected probability 0.200)

## 231: backend/echolens/investigator/specialists.py, backend/echolens/investigator/state.py

Scope: investigation_and_budget; status: reviewed.

- Lines 1–80 (backend/echolens/investigator/specialists.py)
- Lines 1–60 (backend/echolens/investigator/state.py)
- runtime_error_risk: not_detected (confidence 0.020; detected probability 0.330)
- correctness_risk: insufficient_context (confidence 0.480; detected probability 0.120)
- security_risk: insufficient_context (confidence 0.260; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.340; detected probability 0.130)
- no_major_issue: insufficient_context (confidence 0.210; detected probability 0.110)

## 232: backend/echolens/investigator/state.py, backend/echolens/llm/client.py

Scope: investigation_and_budget; status: reviewed.

- Lines 1–60 (backend/echolens/investigator/state.py)
- Lines 1–131 (backend/echolens/llm/client.py)
- runtime_error_risk: detected (confidence 0.210; detected probability 0.480)
- correctness_risk: detected (confidence 0.360; detected probability 0.570)
- security_risk: not_detected (confidence 0.260; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.200; detected probability 0.370)
- no_major_issue: not_detected (confidence 0.200; detected probability 0.280)

## 233: backend/echolens/llm/client.py, backend/echolens/llm/openai_client.py

Scope: investigation_and_budget; status: reviewed.

- Lines 1–131 (backend/echolens/llm/client.py)
- Lines 1–167 (backend/echolens/llm/openai_client.py)
- runtime_error_risk: detected (confidence 0.590; detected probability 0.730)
- correctness_risk: detected (confidence 0.510; detected probability 0.680)
- security_risk: not_detected (confidence 0.560; detected probability 0.030)
- maintainability_risk: detected (confidence 0.210; detected probability 0.470)
- no_major_issue: not_detected (confidence 0.320; detected probability 0.300)

## 234: backend/echolens/collectors/app_store.py, backend/echolens/collectors/base.py

Scope: data_collection; status: reviewed.

- Lines 1–135 (backend/echolens/collectors/app_store.py)
- Lines 1–172 (backend/echolens/collectors/base.py)
- runtime_error_risk: detected (confidence 0.360; detected probability 0.580)
- correctness_risk: detected (confidence 0.370; detected probability 0.580)
- security_risk: not_detected (confidence 0.520; detected probability 0.060)
- maintainability_risk: not_detected (confidence 0.280; detected probability 0.410)
- no_major_issue: not_detected (confidence 0.330; detected probability 0.320)

## 235: backend/echolens/collectors/base.py, backend/echolens/collectors/chrome_web_store.py

Scope: data_collection; status: reviewed.

- Lines 1–172 (backend/echolens/collectors/base.py)
- Lines 1–143 (backend/echolens/collectors/chrome_web_store.py)
- runtime_error_risk: detected (confidence 0.460; detected probability 0.640)
- correctness_risk: detected (confidence 0.530; detected probability 0.690)
- security_risk: not_detected (confidence 0.520; detected probability 0.030)
- maintainability_risk: detected (confidence 0.460; detected probability 0.650)
- no_major_issue: not_detected (confidence 0.210; detected probability 0.400)

## 236: backend/echolens/collectors/chrome_web_store.py, backend/echolens/collectors/feedback_base.py

Scope: data_collection; status: reviewed.

- Lines 1–143 (backend/echolens/collectors/chrome_web_store.py)
- Lines 1–111 (backend/echolens/collectors/feedback_base.py)
- runtime_error_risk: detected (confidence 0.510; detected probability 0.680)
- correctness_risk: detected (confidence 0.540; detected probability 0.700)
- security_risk: not_detected (confidence 0.530; detected probability 0.030)
- maintainability_risk: detected (confidence 0.360; detected probability 0.570)
- no_major_issue: not_detected (confidence 0.180; detected probability 0.360)

## 237: backend/echolens/collectors/feedback_base.py, backend/echolens/collectors/github.py

Scope: data_collection; status: reviewed.

- Lines 1–111 (backend/echolens/collectors/feedback_base.py)
- Lines 1–183 (backend/echolens/collectors/github.py)
- runtime_error_risk: detected (confidence 0.240; detected probability 0.500)
- correctness_risk: detected (confidence 0.280; detected probability 0.520)
- security_risk: not_detected (confidence 0.360; detected probability 0.090)
- maintainability_risk: not_detected (confidence 0.300; detected probability 0.370)
- no_major_issue: not_detected (confidence 0.270; detected probability 0.280)

## 238: backend/echolens/collectors/github.py, backend/echolens/collectors/github_extra.py

Scope: data_collection; status: reviewed.

- Lines 1–183 (backend/echolens/collectors/github.py)
- Lines 1–219 (backend/echolens/collectors/github_extra.py)
- runtime_error_risk: detected (confidence 0.460; detected probability 0.640)
- correctness_risk: detected (confidence 0.690; detected probability 0.790)
- security_risk: not_detected (confidence 0.390; detected probability 0.120)
- maintainability_risk: detected (confidence 0.310; detected probability 0.540)
- no_major_issue: not_detected (confidence 0.190; detected probability 0.360)

## 239: backend/echolens/collectors/github_extra.py, backend/echolens/collectors/hacker_news.py

Scope: data_collection; status: reviewed.

- Lines 1–219 (backend/echolens/collectors/github_extra.py)
- Lines 1–82 (backend/echolens/collectors/hacker_news.py)
- runtime_error_risk: detected (confidence 0.560; detected probability 0.700)
- correctness_risk: detected (confidence 0.630; detected probability 0.760)
- security_risk: not_detected (confidence 0.500; detected probability 0.080)
- maintainability_risk: detected (confidence 0.260; detected probability 0.510)
- no_major_issue: not_detected (confidence 0.170; detected probability 0.390)

## 240: backend/echolens/collectors/hacker_news.py, backend/echolens/collectors/play_store.py

Scope: data_collection; status: reviewed.

- Lines 1–82 (backend/echolens/collectors/hacker_news.py)
- Lines 1–117 (backend/echolens/collectors/play_store.py)
- runtime_error_risk: detected (confidence 0.630; detected probability 0.750)
- correctness_risk: detected (confidence 0.660; detected probability 0.770)
- security_risk: not_detected (confidence 0.550; detected probability 0.080)
- maintainability_risk: detected (confidence 0.360; detected probability 0.570)
- no_major_issue: not_detected (confidence 0.300; detected probability 0.370)

## 241: backend/echolens/collectors/play_store.py, backend/echolens/collectors/registry.py

Scope: data_collection; status: reviewed.

- Lines 1–117 (backend/echolens/collectors/play_store.py)
- Lines 1–270 (backend/echolens/collectors/registry.py)
- runtime_error_risk: detected (confidence 0.390; detected probability 0.590)
- correctness_risk: detected (confidence 0.450; detected probability 0.630)
- security_risk: not_detected (confidence 0.480; detected probability 0.080)
- maintainability_risk: detected (confidence 0.320; detected probability 0.540)
- no_major_issue: not_detected (confidence 0.140; detected probability 0.420)

## 242: backend/echolens/collectors/registry.py, backend/echolens/collectors/scheduler.py

Scope: data_collection; status: reviewed.

- Lines 1–270 (backend/echolens/collectors/registry.py)
- Lines 1–65 (backend/echolens/collectors/scheduler.py)
- runtime_error_risk: detected (confidence 0.340; detected probability 0.560)
- correctness_risk: detected (confidence 0.230; detected probability 0.480)
- security_risk: not_detected (confidence 0.370; detected probability 0.040)
- maintainability_risk: detected (confidence 0.280; detected probability 0.520)
- no_major_issue: not_detected (confidence 0.110; detected probability 0.300)

## 243: backend/echolens/collectors/scheduler.py, backend/echolens/collectors/stack_overflow.py

Scope: data_collection; status: reviewed.

- Lines 1–65 (backend/echolens/collectors/scheduler.py)
- Lines 1–89 (backend/echolens/collectors/stack_overflow.py)
- runtime_error_risk: detected (confidence 0.420; detected probability 0.620)
- correctness_risk: detected (confidence 0.370; detected probability 0.590)
- security_risk: not_detected (confidence 0.330; detected probability 0.070)
- maintainability_risk: detected (confidence 0.350; detected probability 0.570)
- no_major_issue: detected (confidence 0.050; detected probability 0.360)

## 244: backend/echolens/collectors/stack_overflow.py, backend/echolens/db/migrate.py

Scope: data_collection; status: reviewed.

- Lines 1–89 (backend/echolens/collectors/stack_overflow.py)
- Lines 1–122 (backend/echolens/db/migrate.py)
- runtime_error_risk: detected (confidence 0.470; detected probability 0.640)
- correctness_risk: detected (confidence 0.280; detected probability 0.520)
- security_risk: not_detected (confidence 0.420; detected probability 0.050)
- maintainability_risk: not_detected (confidence 0.140; detected probability 0.380)
- no_major_issue: not_detected (confidence 0.140; detected probability 0.290)

## 245: backend/echolens/db/migrate.py, backend/echolens/db/models.py

Scope: data_collection; status: reviewed.

- Lines 1–122 (backend/echolens/db/migrate.py)
- Lines 1–170 (backend/echolens/db/models.py)
- runtime_error_risk: detected (confidence 0.360; detected probability 0.580)
- correctness_risk: detected (confidence 0.290; detected probability 0.520)
- security_risk: not_detected (confidence 0.080; detected probability 0.280)
- maintainability_risk: detected (confidence 0.470; detected probability 0.650)
- no_major_issue: detected (confidence 0.080; detected probability 0.390)

## 246: backend/echolens/db/migrate.py, backend/echolens/db/models.py

Scope: data_collection; status: reviewed.

- Lines 1–122 (backend/echolens/db/migrate.py)
- Lines 342–492 (backend/echolens/db/models.py)
- runtime_error_risk: detected (confidence 0.270; detected probability 0.510)
- correctness_risk: insufficient_context (confidence 0.140; detected probability 0.380)
- security_risk: insufficient_context (confidence 0.240; detected probability 0.100)
- maintainability_risk: detected (confidence 0.230; detected probability 0.480)
- no_major_issue: insufficient_context (confidence 0.090; detected probability 0.240)

## 247: backend/echolens/db/models.py, backend/echolens/db/session.py

Scope: data_collection; status: reviewed.

- Lines 1–170 (backend/echolens/db/models.py)
- Lines 1–171 (backend/echolens/db/session.py)
- runtime_error_risk: detected (confidence 0.420; detected probability 0.620)
- correctness_risk: insufficient_context (confidence 0.150; detected probability 0.290)
- security_risk: insufficient_context (confidence 0.090; detected probability 0.240)
- maintainability_risk: detected (confidence 0.500; detected probability 0.670)
- no_major_issue: not_detected (confidence 0.100; detected probability 0.350)

## 248: backend/echolens/db/models.py, backend/echolens/db/session.py

Scope: data_collection; status: reviewed.

- Lines 342–492 (backend/echolens/db/models.py)
- Lines 1–171 (backend/echolens/db/session.py)
- runtime_error_risk: detected (confidence 0.320; detected probability 0.550)
- correctness_risk: insufficient_context (confidence 0.280; detected probability 0.230)
- security_risk: insufficient_context (confidence 0.130; detected probability 0.240)
- maintainability_risk: detected (confidence 0.320; detected probability 0.550)
- no_major_issue: not_detected (confidence 0.110; detected probability 0.290)

## 249: frontend/src/api.ts, frontend/src/screens/CaseDetail.tsx

Scope: frontend_case_review; status: reviewed.

- Lines 1–325 (frontend/src/api.ts)
- Lines 1–125 (frontend/src/screens/CaseDetail.tsx)
- runtime_error_risk: detected (confidence 0.150; detected probability 0.430)
- correctness_risk: insufficient_context (confidence 0.320; detected probability 0.300)
- security_risk: insufficient_context (confidence 0.400; detected probability 0.280)
- maintainability_risk: detected (confidence 0.390; detected probability 0.590)
- no_major_issue: detected (confidence 0.200; detected probability 0.470)

## 250: frontend/src/api.ts, frontend/src/screens/CaseDetail.tsx

Scope: frontend_case_review; status: reviewed.

- Lines 651–802 (frontend/src/api.ts)
- Lines 1–251 (frontend/src/screens/CaseDetail.tsx)
- runtime_error_risk: detected (confidence 0.110; detected probability 0.400)
- correctness_risk: insufficient_context (confidence 0.110; detected probability 0.280)
- security_risk: insufficient_context (confidence 0.380; detected probability 0.070)
- maintainability_risk: detected (confidence 0.210; detected probability 0.470)
- no_major_issue: detected (confidence 0.190; detected probability 0.460)

## 251: frontend/src/screens/CaseDetail.tsx, frontend/src/screens/case/DiscussionTab.tsx

Scope: frontend_case_review; status: reviewed.

- Lines 1–251 (frontend/src/screens/CaseDetail.tsx)
- Lines 1–188 (frontend/src/screens/case/DiscussionTab.tsx)
- runtime_error_risk: not_detected (confidence 0.260; detected probability 0.280)
- correctness_risk: not_detected (confidence 0.360; detected probability 0.150)
- security_risk: insufficient_context (confidence 0.390; detected probability 0.020)
- maintainability_risk: not_detected (confidence 0.380; detected probability 0.320)
- no_major_issue: not_detected (confidence 0.410; detected probability 0.200)

## 252: frontend/src/screens/case/DiscussionTab.tsx, frontend/src/screens/case/EngineeringTab.tsx

Scope: frontend_case_review; status: reviewed.

- Lines 1–188 (frontend/src/screens/case/DiscussionTab.tsx)
- Lines 1–189 (frontend/src/screens/case/EngineeringTab.tsx)
- runtime_error_risk: not_detected (confidence 0.060; detected probability 0.360)
- correctness_risk: insufficient_context (confidence 0.290; detected probability 0.020)
- security_risk: not_detected (confidence 0.290; detected probability 0.030)
- maintainability_risk: not_detected (confidence 0.460; detected probability 0.270)
- no_major_issue: not_detected (confidence 0.280; detected probability 0.180)

## 253: frontend/src/screens/case/EngineeringTab.tsx, frontend/src/screens/case/EvidenceTab.tsx

Scope: frontend_case_review; status: reviewed.

- Lines 1–189 (frontend/src/screens/case/EngineeringTab.tsx)
- Lines 1–86 (frontend/src/screens/case/EvidenceTab.tsx)
- runtime_error_risk: not_detected (confidence 0.070; detected probability 0.330)
- correctness_risk: not_detected (confidence 0.230; detected probability 0.030)
- security_risk: not_detected (confidence 0.570; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.680; detected probability 0.080)
- no_major_issue: not_detected (confidence 0.370; detected probability 0.100)

## 254: frontend/src/screens/case/EvidenceTab.tsx, frontend/src/screens/case/FindingTab.tsx

Scope: frontend_case_review; status: reviewed.

- Lines 1–86 (frontend/src/screens/case/EvidenceTab.tsx)
- Lines 1–203 (frontend/src/screens/case/FindingTab.tsx)
- runtime_error_risk: not_detected (confidence 0.320; detected probability 0.200)
- correctness_risk: not_detected (confidence 0.350; detected probability 0.050)
- security_risk: not_detected (confidence 0.620; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.510; detected probability 0.140)
- no_major_issue: not_detected (confidence 0.240; detected probability 0.160)

## 255: frontend/src/screens/case/EvidenceTab.tsx, frontend/src/screens/case/FindingTab.tsx

Scope: frontend_case_review; status: reviewed.

- Lines 1–86 (frontend/src/screens/case/EvidenceTab.tsx)
- Lines 407–479 (frontend/src/screens/case/FindingTab.tsx)
- runtime_error_risk: not_detected (confidence 0.340; detected probability 0.120)
- correctness_risk: insufficient_context (confidence 0.270; detected probability 0.030)
- security_risk: not_detected (confidence 0.480; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.540; detected probability 0.070)
- no_major_issue: not_detected (confidence 0.340; detected probability 0.080)

## 256: frontend/src/screens/case/FindingTab.tsx, frontend/src/screens/case/HistoryTab.tsx

Scope: frontend_case_review; status: reviewed.

- Lines 1–203 (frontend/src/screens/case/FindingTab.tsx)
- Lines 1–91 (frontend/src/screens/case/HistoryTab.tsx)
- runtime_error_risk: not_detected (confidence 0.360; detected probability 0.200)
- correctness_risk: not_detected (confidence 0.270; detected probability 0.050)
- security_risk: not_detected (confidence 0.570; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.590; detected probability 0.130)
- no_major_issue: not_detected (confidence 0.330; detected probability 0.120)

## 257: frontend/src/screens/case/FindingTab.tsx, frontend/src/screens/case/HistoryTab.tsx

Scope: frontend_case_review; status: reviewed.

- Lines 407–479 (frontend/src/screens/case/FindingTab.tsx)
- Lines 1–91 (frontend/src/screens/case/HistoryTab.tsx)
- runtime_error_risk: not_detected (confidence 0.420; detected probability 0.090)
- correctness_risk: not_detected (confidence 0.280; detected probability 0.000)
- security_risk: not_detected (confidence 0.630; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.660; detected probability 0.050)
- no_major_issue: not_detected (confidence 0.400; detected probability 0.070)

## 258: frontend/src/screens/case/HistoryTab.tsx, frontend/src/screens/case/TraceTab.tsx

Scope: frontend_case_review; status: reviewed.

- Lines 1–91 (frontend/src/screens/case/HistoryTab.tsx)
- Lines 1–193 (frontend/src/screens/case/TraceTab.tsx)
- runtime_error_risk: not_detected (confidence 0.080; detected probability 0.270)
- correctness_risk: insufficient_context (confidence 0.230; detected probability 0.170)
- security_risk: not_detected (confidence 0.440; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.230; detected probability 0.250)
- no_major_issue: insufficient_context (confidence 0.250; detected probability 0.160)

## 259: frontend/src/screens/case/HistoryTab.tsx, frontend/src/screens/case/TraceTab.tsx

Scope: frontend_case_review; status: reviewed.

- Lines 1–91 (frontend/src/screens/case/HistoryTab.tsx)
- Lines 387–423 (frontend/src/screens/case/TraceTab.tsx)
- runtime_error_risk: not_detected (confidence 0.440; detected probability 0.100)
- correctness_risk: not_detected (confidence 0.280; detected probability 0.010)
- security_risk: not_detected (confidence 0.670; detected probability 0.010)
- maintainability_risk: not_detected (confidence 0.480; detected probability 0.130)
- no_major_issue: not_detected (confidence 0.360; detected probability 0.070)

## Skipped source

- backend/echolens/api/__init__.py: empty
- backend/echolens/collectors/__init__.py: empty
- backend/echolens/db/__init__.py: empty
- backend/echolens/detector/__init__.py: empty
- backend/echolens/investigator/__init__.py: empty
- backend/echolens/llm/__init__.py: empty
- backend/echolens/orchestrator/__init__.py: empty
- backend/echolens/recommender/__init__.py: empty
- backend/echolens/search/__init__.py: empty
- backend/echolens/synthetic/__init__.py: empty
- backend/echolens/tools/__init__.py: empty
- backend/tests/__init__.py: empty
- frontend/src/tokens.css: excluded_path
- frontend/src/vite-env.d.ts: excluded_path
