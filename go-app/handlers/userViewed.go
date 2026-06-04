package handlers

import (
	"database/sql"
	"encoding/json"
	"go-app/config"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

type AddViewedItemRequest struct {
	Item string `json:"item"`
}

type ViewedItem struct {
	Item  string `json:"item"`
	Count int    `json:"count"`
}

func AddViewedItem(c *gin.Context) {
	db := config.GetDB()
	defer db.Close()

	username := c.GetString("username")
	if username == "" {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}

	var req AddViewedItemRequest

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}

	item := strings.TrimSpace(normalizePersian(req.Item))
	if item == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "item is required"})
		return
	}

	tx, err := db.Begin()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "transaction error"})
		return
	}
	defer tx.Rollback()

	var viewedItemsRaw sql.NullString

	err = tx.QueryRow(`
		SELECT [ViewedItems]
		FROM [codal].[dbo].[Users] WITH (UPDLOCK, ROWLOCK)
		WHERE [UserName] = @p1
	`, username).Scan(&viewedItemsRaw)

	if err == sql.ErrNoRows {
		c.JSON(http.StatusNotFound, gin.H{"error": "user not found"})
		return
	}

	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "select error: " + err.Error()})
		return
	}

	viewedItems := []ViewedItem{}

	if viewedItemsRaw.Valid && strings.TrimSpace(viewedItemsRaw.String) != "" {
		if err := json.Unmarshal([]byte(viewedItemsRaw.String), &viewedItems); err != nil {
			viewedItems = []ViewedItem{}
		}
	}

	found := false

	for i := range viewedItems {
		existingItem := strings.TrimSpace(normalizePersian(viewedItems[i].Item))

		if existingItem == item {
			viewedItems[i].Count++
			found = true
			break
		}
	}

	if !found {
		viewedItems = append(viewedItems, ViewedItem{
			Item:  item,
			Count: 1,
		})
	}

	updatedJSON, err := json.Marshal(viewedItems)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "json marshal error"})
		return
	}

	_, err = tx.Exec(`
		UPDATE [codal].[dbo].[Users]
		SET [ViewedItems] = @p1
		WHERE [UserName] = @p2
	`, string(updatedJSON), username)

	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "update error: " + err.Error()})
		return
	}

	if err := tx.Commit(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "commit error"})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"message":     "viewed item updated",
		"viewedItems": viewedItems,
	})
}
