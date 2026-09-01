; ModuleID = '/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/read_return.c'
source_filename = "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/read_return.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: nounwind uwtable
define dso_local void @read_return_update(ptr noundef %0, i32 noundef %1) local_unnamed_addr #0 !dbg !14 {
  tail call void @llvm.dbg.value(metadata ptr %0, metadata !24, metadata !DIExpression()), !dbg !27
  tail call void @llvm.dbg.value(metadata i32 %1, metadata !25, metadata !DIExpression()), !dbg !27
  call void @llvm.dbg.value(metadata ptr %0, metadata !28, metadata !DIExpression()), !dbg !33
  %3 = getelementptr inbounds i8, ptr %0, i64 40, !dbg !35
  call void @llvm.dbg.value(metadata ptr %3, metadata !36, metadata !DIExpression()), !dbg !46
  %4 = tail call i32 asm sideeffect "movl $1,$0", "=r,*m,~{memory},~{dirflag},~{fpsr},~{flags}"(ptr nonnull elementtype(i32) %3) #2, !dbg !48, !srcloc !49
  call void @llvm.dbg.value(metadata i32 %4, metadata !45, metadata !DIExpression()), !dbg !46
  tail call void @llvm.dbg.value(metadata i32 %4, metadata !26, metadata !DIExpression()), !dbg !27
  %5 = or i32 %4, %1, !dbg !50
  call void @llvm.dbg.value(metadata i32 %5, metadata !51, metadata !DIExpression()), !dbg !58
  call void @llvm.dbg.value(metadata ptr %3, metadata !57, metadata !DIExpression()), !dbg !58
  tail call void asm sideeffect "movl $0,$1", "r,*m,~{memory},~{dirflag},~{fpsr},~{flags}"(i32 %5, ptr nonnull elementtype(i32) %3) #2, !dbg !60, !srcloc !61
  ret void, !dbg !62
}

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare void @llvm.dbg.value(metadata, metadata, metadata) #1

attributes #0 = { nounwind uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #1 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }
attributes #2 = { nounwind }

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!6, !7, !8, !9, !10, !11, !12}
!llvm.ident = !{!13}

!0 = distinct !DICompileUnit(language: DW_LANG_C11, file: !1, producer: "Ubuntu clang version 18.1.3 (1ubuntu1)", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug, retainedTypes: !2, splitDebugInlining: false, nameTableKind: None)
!1 = !DIFile(filename: "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/read_return.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "74abe636bfe831f9a909f057e92f4cea")
!2 = !{!3}
!3 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !4, size: 64)
!4 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: !5)
!5 = !DIBasicType(name: "unsigned int", size: 32, encoding: DW_ATE_unsigned)
!6 = !{i32 7, !"Dwarf Version", i32 5}
!7 = !{i32 2, !"Debug Info Version", i32 3}
!8 = !{i32 1, !"wchar_size", i32 4}
!9 = !{i32 8, !"PIC Level", i32 2}
!10 = !{i32 7, !"PIE Level", i32 2}
!11 = !{i32 7, !"uwtable", i32 2}
!12 = !{i32 7, !"debug-info-assignment-tracking", i1 true}
!13 = !{!"Ubuntu clang version 18.1.3 (1ubuntu1)"}
!14 = distinct !DISubprogram(name: "read_return_update", scope: !15, file: !15, line: 10, type: !16, scopeLine: 11, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !23)
!15 = !DIFile(filename: "qa/tests/fixtures/read_return.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "74abe636bfe831f9a909f057e92f4cea")
!16 = !DISubroutineType(types: !17)
!17 = !{null, !18, !19}
!18 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: null, size: 64)
!19 = !DIDerivedType(tag: DW_TAG_typedef, name: "u32", file: !20, line: 21, baseType: !21)
!20 = !DIFile(filename: "vendor/linux/include/asm-generic/int-ll64.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "12ca7bdb629352cc4c9a492f86b435a7")
!21 = !DIDerivedType(tag: DW_TAG_typedef, name: "__u32", file: !22, line: 27, baseType: !5)
!22 = !DIFile(filename: "vendor/linux/include/uapi/asm-generic/int-ll64.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "f4d0ec5bcdd84e825a78a7add39d54dd")
!23 = !{!24, !25, !26}
!24 = !DILocalVariable(name: "base", arg: 1, scope: !14, file: !15, line: 10, type: !18)
!25 = !DILocalVariable(name: "mask", arg: 2, scope: !14, file: !15, line: 10, type: !19)
!26 = !DILocalVariable(name: "value", scope: !14, file: !15, line: 12, type: !19)
!27 = !DILocation(line: 0, scope: !14)
!28 = !DILocalVariable(name: "base", arg: 1, scope: !29, file: !15, line: 5, type: !18)
!29 = distinct !DISubprogram(name: "read_return_helper", scope: !15, file: !15, line: 5, type: !30, scopeLine: 6, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagLocalToUnit | DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !32)
!30 = !DISubroutineType(types: !31)
!31 = !{!19, !18}
!32 = !{!28}
!33 = !DILocation(line: 0, scope: !29, inlinedAt: !34)
!34 = distinct !DILocation(line: 12, column: 14, scope: !14)
!35 = !DILocation(line: 7, column: 20, scope: !29, inlinedAt: !34)
!36 = !DILocalVariable(name: "addr", arg: 1, scope: !37, file: !38, line: 59, type: !41)
!37 = distinct !DISubprogram(name: "readl", scope: !38, file: !38, line: 59, type: !39, scopeLine: 59, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagLocalToUnit | DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !44)
!38 = !DIFile(filename: "vendor/linux/arch/x86/include/asm/io.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "7255a33f32535fc68bd0d1cd99111699")
!39 = !DISubroutineType(types: !40)
!40 = !{!5, !41}
!41 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !42, size: 64)
!42 = !DIDerivedType(tag: DW_TAG_const_type, baseType: !43)
!43 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: null)
!44 = !{!36, !45}
!45 = !DILocalVariable(name: "ret", scope: !37, file: !38, line: 59, type: !5)
!46 = !DILocation(line: 0, scope: !37, inlinedAt: !47)
!47 = distinct !DILocation(line: 7, column: 9, scope: !29, inlinedAt: !34)
!48 = !DILocation(line: 59, column: 1, scope: !37, inlinedAt: !47)
!49 = !{i64 2149611349}
!50 = !DILocation(line: 14, column: 15, scope: !14)
!51 = !DILocalVariable(name: "val", arg: 1, scope: !52, file: !38, line: 67, type: !5)
!52 = distinct !DISubprogram(name: "writel", scope: !38, file: !38, line: 67, type: !53, scopeLine: 67, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagLocalToUnit | DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !56)
!53 = !DISubroutineType(types: !54)
!54 = !{null, !5, !55}
!55 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !43, size: 64)
!56 = !{!51, !57}
!57 = !DILocalVariable(name: "addr", arg: 2, scope: !52, file: !38, line: 67, type: !55)
!58 = !DILocation(line: 0, scope: !52, inlinedAt: !59)
!59 = distinct !DILocation(line: 14, column: 2, scope: !14)
!60 = !DILocation(line: 67, column: 1, scope: !52, inlinedAt: !59)
!61 = !{i64 2149613742}
!62 = !DILocation(line: 15, column: 1, scope: !14)
