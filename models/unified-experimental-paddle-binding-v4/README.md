# PaddleOCR-VL binding-loss continuation

Experimental single-network LoRA; rejected for production replacement. Base PaddlePaddle/PaddleOCR-VL-1.6, revision c5630abae1d940eafe0697512a0325494b02ab42, Apache-2.0. Continuation from pilot step 160, optimizer reset, 300 steps on 420 fictional pages, full BF16 + 1 MP. Type/key loss weights 8/4. Viewed development 25/56 vs 45/56 baseline, lost 22, new 2. Organizer and private real-case qualification stored separately. No control answers used for training.

Adapter SHA256: 4dd105bb0a88962caf9b15a7b5e6620006c45653108cd7027dfc7f1bd6e36458
