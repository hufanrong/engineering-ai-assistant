import {
  BadRequestException,
  Inject,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import {
  DRIZZLE_DATABASE,
  PostgresJsDatabase,
} from '@lark-apaas/fullstack-nestjs-core';
import { count, desc, eq, ilike, or } from 'drizzle-orm';

import {
  platformMaterial,
  platformProcess,
  platformStandard,
} from '@server/database/schema';
import type {
  CreatePlatformMaterialRequest,
  CreatePlatformProcessRequest,
  CreatePlatformStandardRequest,
  PlatformListResponse,
  PlatformMaterialItem,
  PlatformProcessItem,
  PlatformStandardItem,
  UpdatePlatformMaterialRequest,
  UpdatePlatformProcessRequest,
  UpdatePlatformStandardRequest,
} from '@shared/api.interface';

@Injectable()
export class PlatformDataService {
  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
  ) {}

  async listStandards(
    keyword: string | undefined,
    offset: number,
    limit: number,
  ): Promise<PlatformListResponse<PlatformStandardItem>> {
    const pattern = this.toPattern(keyword);
    const conditions = pattern
      ? or(
          ilike(platformStandard.name, pattern),
          ilike(platformStandard.standardCode, pattern),
        )
      : undefined;
    const [rows, totals] = await Promise.all([
      this.db
        .select()
        .from(platformStandard)
        .where(conditions)
        .orderBy(desc(platformStandard.createdAt))
        .limit(limit)
        .offset(offset),
      this.db.select({ value: count() }).from(platformStandard).where(conditions),
    ]);
    const items: PlatformStandardItem[] = rows.map((row) => ({
      id: row.id,
      standardCode: row.standardCode,
      name: row.name,
      publishDate: row.publishDate ?? undefined,
      category: row.category ?? undefined,
      content: row.content ?? undefined,
    }));
    return { items, total: Number(totals[0]?.value ?? 0) };
  }

  async createStandard(
    dto: CreatePlatformStandardRequest,
  ): Promise<PlatformStandardItem> {
    const inserted = await this.db
      .insert(platformStandard)
      .values({
        standardCode: dto.standardCode,
        name: dto.name,
        publishDate: dto.publishDate ?? null,
        category: dto.category ?? null,
        content: dto.content ?? null,
      })
      .returning();
    const row = inserted[0];
    return {
      id: row.id,
      standardCode: row.standardCode,
      name: row.name,
      publishDate: row.publishDate ?? undefined,
      category: row.category ?? undefined,
      content: row.content ?? undefined,
    };
  }

  async updateStandard(
    id: string,
    dto: UpdatePlatformStandardRequest,
  ): Promise<{ id: string }> {
    const patch: Partial<typeof platformStandard.$inferInsert> = {};
    if (dto.standardCode !== undefined) patch.standardCode = dto.standardCode;
    if (dto.name !== undefined) patch.name = dto.name;
    if (dto.publishDate !== undefined) patch.publishDate = dto.publishDate;
    if (dto.category !== undefined) patch.category = dto.category;
    if (dto.content !== undefined) patch.content = dto.content;
    if (Object.keys(patch).length === 0) {
      throw new BadRequestException('未提供可更新字段');
    }
    patch.updatedAt = new Date();
    const updated = await this.db
      .update(platformStandard)
      .set(patch)
      .where(eq(platformStandard.id, id))
      .returning({ id: platformStandard.id });
    if (updated.length === 0) throw new NotFoundException('规范不存在');
    return { id: updated[0].id };
  }

  async deleteStandard(id: string): Promise<{ id: string }> {
    const deleted = await this.db
      .delete(platformStandard)
      .where(eq(platformStandard.id, id))
      .returning({ id: platformStandard.id });
    if (deleted.length === 0) throw new NotFoundException('规范不存在');
    return { id: deleted[0].id };
  }

  async listMaterials(
    keyword: string | undefined,
    offset: number,
    limit: number,
  ): Promise<PlatformListResponse<PlatformMaterialItem>> {
    const pattern = this.toPattern(keyword);
    const conditions = pattern
      ? or(
          ilike(platformMaterial.name, pattern),
          ilike(platformMaterial.standardCode, pattern),
        )
      : undefined;
    const [rows, totals] = await Promise.all([
      this.db
        .select()
        .from(platformMaterial)
        .where(conditions)
        .orderBy(desc(platformMaterial.createdAt))
        .limit(limit)
        .offset(offset),
      this.db.select({ value: count() }).from(platformMaterial).where(conditions),
    ]);
    const items: PlatformMaterialItem[] = rows.map((row) => ({
      id: row.id,
      name: row.name,
      materialGrade: row.materialGrade ?? undefined,
      spec: row.spec ?? undefined,
      standardCode: row.standardCode ?? undefined,
      category: row.category ?? undefined,
    }));
    return { items, total: Number(totals[0]?.value ?? 0) };
  }

  async createMaterial(
    dto: CreatePlatformMaterialRequest,
  ): Promise<PlatformMaterialItem> {
    const inserted = await this.db
      .insert(platformMaterial)
      .values({
        name: dto.name,
        materialGrade: dto.materialGrade ?? null,
        spec: dto.spec ?? null,
        standardCode: dto.standardCode ?? null,
        category: dto.category ?? null,
      })
      .returning();
    const row = inserted[0];
    return {
      id: row.id,
      name: row.name,
      materialGrade: row.materialGrade ?? undefined,
      spec: row.spec ?? undefined,
      standardCode: row.standardCode ?? undefined,
      category: row.category ?? undefined,
    };
  }

  async updateMaterial(
    id: string,
    dto: UpdatePlatformMaterialRequest,
  ): Promise<{ id: string }> {
    const patch: Partial<typeof platformMaterial.$inferInsert> = {};
    if (dto.name !== undefined) patch.name = dto.name;
    if (dto.materialGrade !== undefined) patch.materialGrade = dto.materialGrade;
    if (dto.spec !== undefined) patch.spec = dto.spec;
    if (dto.standardCode !== undefined) patch.standardCode = dto.standardCode;
    if (dto.category !== undefined) patch.category = dto.category;
    if (Object.keys(patch).length === 0) {
      throw new BadRequestException('未提供可更新字段');
    }
    patch.updatedAt = new Date();
    const updated = await this.db
      .update(platformMaterial)
      .set(patch)
      .where(eq(platformMaterial.id, id))
      .returning({ id: platformMaterial.id });
    if (updated.length === 0) throw new NotFoundException('材料不存在');
    return { id: updated[0].id };
  }

  async deleteMaterial(id: string): Promise<{ id: string }> {
    const deleted = await this.db
      .delete(platformMaterial)
      .where(eq(platformMaterial.id, id))
      .returning({ id: platformMaterial.id });
    if (deleted.length === 0) throw new NotFoundException('材料不存在');
    return { id: deleted[0].id };
  }

  async listProcesses(
    keyword: string | undefined,
    offset: number,
    limit: number,
  ): Promise<PlatformListResponse<PlatformProcessItem>> {
    const pattern = this.toPattern(keyword);
    const conditions = pattern ? ilike(platformProcess.name, pattern) : undefined;
    const [rows, totals] = await Promise.all([
      this.db
        .select()
        .from(platformProcess)
        .where(conditions)
        .orderBy(desc(platformProcess.createdAt))
        .limit(limit)
        .offset(offset),
      this.db.select({ value: count() }).from(platformProcess).where(conditions),
    ]);
    const items: PlatformProcessItem[] = rows.map((row) => ({
      id: row.id,
      name: row.name,
      scope: row.scope ?? undefined,
      description: row.description ?? undefined,
      category: row.category ?? undefined,
    }));
    return { items, total: Number(totals[0]?.value ?? 0) };
  }

  async createProcess(
    dto: CreatePlatformProcessRequest,
  ): Promise<PlatformProcessItem> {
    const inserted = await this.db
      .insert(platformProcess)
      .values({
        name: dto.name,
        scope: dto.scope ?? null,
        description: dto.description ?? null,
        category: dto.category ?? null,
      })
      .returning();
    const row = inserted[0];
    return {
      id: row.id,
      name: row.name,
      scope: row.scope ?? undefined,
      description: row.description ?? undefined,
      category: row.category ?? undefined,
    };
  }

  async updateProcess(
    id: string,
    dto: UpdatePlatformProcessRequest,
  ): Promise<{ id: string }> {
    const patch: Partial<typeof platformProcess.$inferInsert> = {};
    if (dto.name !== undefined) patch.name = dto.name;
    if (dto.scope !== undefined) patch.scope = dto.scope;
    if (dto.description !== undefined) patch.description = dto.description;
    if (dto.category !== undefined) patch.category = dto.category;
    if (Object.keys(patch).length === 0) {
      throw new BadRequestException('未提供可更新字段');
    }
    patch.updatedAt = new Date();
    const updated = await this.db
      .update(platformProcess)
      .set(patch)
      .where(eq(platformProcess.id, id))
      .returning({ id: platformProcess.id });
    if (updated.length === 0) throw new NotFoundException('工艺不存在');
    return { id: updated[0].id };
  }

  async deleteProcess(id: string): Promise<{ id: string }> {
    const deleted = await this.db
      .delete(platformProcess)
      .where(eq(platformProcess.id, id))
      .returning({ id: platformProcess.id });
    if (deleted.length === 0) throw new NotFoundException('工艺不存在');
    return { id: deleted[0].id };
  }

  private toPattern(keyword: string | undefined): string | undefined {
    if (keyword === undefined || keyword.trim() === '') return undefined;
    return `%${keyword.trim()}%`;
  }
}
